"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.memory_management.service import MemoryManagementService
from longmemory.core.common.identifiers import MemoryId
from longmemory.infrastructure.database.schema import SCHEMA_VERSION


class MemoryAccessError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def memory_json(memory):
    return {
        "id": str(memory.id), "subject_id": str(memory.subject_id), "content": memory.content,
        **{key: getattr(memory, key).isoformat() if getattr(memory, key) else None
           for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
        "superseded_by_id": str(memory.superseded_by_id) if memory.superseded_by_id else None,
        "state": "retired" if memory.retired_at else "active",
    }


def details_json(details):
    result = memory_json(details.memory)
    result["sources"] = [{
        "source_message_id": str(source.evidence.source_message_id),
        "source_type": source.evidence.source_type.value,
        "linked_at": source.evidence.linked_at.isoformat(),
        "message": None if source.source_message is None else {
            "role": source.source_message.role.value,
            "content": source.source_message.content,
            "created_at": source.source_message.created_at.isoformat(),
        },
    } for source in details.sources]
    return result


def revision(data):
    """用于删除前再次核对内容及来源，不是鉴权令牌，不替代 CSRF 校验。"""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class MemoryBackend:
    def __init__(self, database: Path | None, *, allow_delete=False, allow_correction=False):
        # 路径只来自启动参数；任何 HTTP 请求都不能选文件或切换数据库。
        self.database = database.resolve() if database is not None else None
        self.allow_delete = allow_delete
        self.allow_correction = allow_correction

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None,
                "allow_correction": self.allow_correction and self.database is not None,
                # 当前两个操作共用同一个显式启动权限，但对前端公开独立能力名，
                # 以后拆分权限时不需要再改变页面语义。
                "allow_change": self.allow_correction and self.database is not None}

    @contextmanager
    def _open(self, *, write_capability=None):
        if self.database is None:
            raise MemoryAccessError("memory_not_configured", 503)
        if not self.database.is_file():
            raise MemoryAccessError("memory_database_missing", 503)
        if write_capability == "delete" and not self.allow_delete:
            raise MemoryAccessError("memory_read_only", 403)
        if write_capability == "correction" and not self.allow_correction:
            raise MemoryAccessError("memory_correction_disabled", 403)
        connection = None
        try:
            # mode=ro/rw 都不创建文件；不用 open_database 或 build_application，
            # 因为它们会初始化/迁移。连接在请求工作线程内创建并关闭。
            write = write_capability is not None
            mode = "rw" if write else "ro"
            connection = sqlite3.connect(self.database.as_uri() + "?mode=" + mode, uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            if not write:
                connection.execute("PRAGMA query_only = ON")
            # 删除先持有写锁，再检查快照和删除，避免核对后又被别的进程改动。
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise MemoryAccessError("memory_schema_unsupported")
            yield connection
        except sqlite3.OperationalError as error:
            primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            code = "memory_busy" if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "memory_database_unavailable"
            raise MemoryAccessError(code, 503) from None
        except (sqlite3.DatabaseError, ValueError, KeyError, TypeError):
            raise MemoryAccessError("memory_database_invalid", 503) from None
        finally:
            if connection is not None:
                # 未提交的读事务、失败写事务均在关闭时回滚；成功删除沿用原用例提交。
                connection.close()

    @staticmethod
    def _service(connection, *, commit_changes=True):
        return MemoryManagementService(
            memory_store=SQLiteMemoryStore(connection, commit_changes=commit_changes),
            conversation_store=SQLiteConversationStore(connection, commit_changes=commit_changes),
        )

    def list_page(self, *, query="", state="active", limit=25, offset=0):
        with self._open() as connection:
            total, items = SQLiteMemoryStore(connection).list_page(query=query, state=state, limit=limit, offset=offset)
            summaries = []
            for item in items:
                row = memory_json(item)
                row["content"] = item.content[:240]
                row["truncated"] = len(item.content) > 240
                summaries.append(row)
            return {"items": summaries, "total": total, "limit": limit, "offset": offset}

    def list_sources(self, *, query="", role="all", link_state="all", limit=25, offset=0):
        """分页读取 L0，并明确它是否已经成为任意 L1 的证据。"""

        with self._open() as connection:
            clauses, parameters = [], []
            if query:
                clauses.append("instr(lower(m.content), lower(?)) > 0")
                parameters.append(query)
            if role != "all":
                clauses.append("m.role = ?")
                parameters.append(role)
            linked = "EXISTS (SELECT 1 FROM memory_evidence e WHERE e.source_message_id = m.id)"
            if link_state == "linked":
                clauses.append(linked)
            elif link_state == "unlinked":
                clauses.append("NOT " + linked)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = connection.execute(
                "SELECT count(*) FROM conversation_messages m" + where,
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT m.id, m.role, m.content, m.created_at,
                       count(DISTINCT e.memory_id) AS linked_memory_count
                FROM conversation_messages m
                LEFT JOIN memory_evidence e ON e.source_message_id = m.id
                """ + where + """
                GROUP BY m.id, m.role, m.content, m.created_at
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
            items = [{
                "id": row["id"],
                "role": row["role"],
                "content": row["content"][:240],
                "truncated": len(row["content"]) > 240,
                "created_at": row["created_at"],
                "linked_memory_count": row["linked_memory_count"],
            } for row in rows]
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_source(self, source_id):
        """读取一条 L0 原文及其派生 L1；未关联也必须作为真实状态返回。"""

        with self._open() as connection:
            source = connection.execute(
                "SELECT id, role, content, created_at FROM conversation_messages WHERE id = ?",
                (source_id,),
            ).fetchone()
            if source is None:
                raise MemoryAccessError("source_message_not_found", 404)
            rows = connection.execute(
                """
                SELECT a.*, e.source_type, e.linked_at
                FROM memory_evidence e
                JOIN atomic_memories a ON a.id = e.memory_id
                WHERE e.source_message_id = ?
                ORDER BY e.linked_at DESC, a.id DESC
                """,
                (source_id,),
            ).fetchall()
            derived = []
            for row in rows:
                item = {
                    "id": row["id"], "subject_id": row["subject_id"], "content": row["content"],
                    **{key: row[key] for key in ("recorded_at", "valid_from", "valid_to", "retired_at")},
                    "superseded_by_id": row["superseded_by_id"],
                    "state": "retired" if row["retired_at"] else "active",
                }
                item.update(source_type=row["source_type"], linked_at=row["linked_at"])
                derived.append(item)
            return {
                "id": source["id"], "role": source["role"], "content": source["content"],
                "created_at": source["created_at"], "derived_memories": derived,
            }

    def get(self, memory_id):
        with self._open() as connection:
            details = self._service(connection).get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            data = details_json(details)
            return {**data, "revision": revision(data)}

    def delete(self, memory_id, expected_revision):
        with self._open(write_capability="delete") as connection:
            service = self._service(connection, commit_changes=False)
            details = service.get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(revision(details_json(details)), expected_revision):
                raise MemoryAccessError("memory_changed")
            # 复用已经测试过的语义：删除 L1 + 来源关联，保留 L0 原始对话。
            # 外键还会解除其他记忆指向此条的取代链接，不冒充完整隐私擦除。
            if not service.delete_memory(MemoryId(memory_id)):
                raise MemoryAccessError("memory_not_found", 404)
            connection.commit()
            return {"deleted": True, "id": memory_id, "l0_preserved": True}

    def correct(self, memory_id, corrected_content, expected_revision):
        """在一个 SQLite 事务中保存纠正来源、新事实和取代关系。"""

        with self._open(write_capability="correction") as connection:
            service = self._service(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.correct_memory(
                    MemoryId(memory_id), corrected_content
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if code.startswith("corrected_content_") else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_correction_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "corrected": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "old_l0_preserved": True,
            }

    def record_change(self, memory_id, new_content, effective_at, expected_revision):
        """在同一事务中记录事实变化及其双时间语义。"""

        with self._open(write_capability="correction") as connection:
            service = self._service(connection, commit_changes=False)
            old_details = service.get_memory(MemoryId(memory_id))
            if old_details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(
                revision(details_json(old_details)), expected_revision
            ):
                raise MemoryAccessError("memory_changed")
            try:
                result = service.record_memory_change(
                    MemoryId(memory_id),
                    new_content,
                    effective_at=datetime.fromisoformat(effective_at),
                )
            except LookupError:
                raise MemoryAccessError("memory_not_found", 404) from None
            except ValueError as error:
                code = str(error)
                status = 400 if (
                    code.startswith("changed_content_")
                    or code.startswith("effective_at_")
                    or code == "occurred_at_timezone_required"
                ) else 409
                raise MemoryAccessError(code, status) from None
            except RuntimeError as error:
                if str(error) == "memory_change_race":
                    raise MemoryAccessError("memory_changed") from None
                raise
            connection.commit()
            return {
                "changed": True,
                "old_memory_id": str(result.old_memory.id),
                "new_memory_id": str(result.new_memory.id),
                "source_message_id": str(result.source_message.id),
                "source_type": result.evidence.source_type.value,
                "effective_at": result.effective_at.isoformat(),
                "old_l0_preserved": True,
            }
