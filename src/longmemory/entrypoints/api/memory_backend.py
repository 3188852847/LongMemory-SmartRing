"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
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
    def __init__(self, database: Path | None, *, allow_delete=False):
        # 路径只来自启动参数；任何 HTTP 请求都不能选文件或切换数据库。
        self.database = database.resolve() if database is not None else None
        self.allow_delete = allow_delete

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None}

    @contextmanager
    def _open(self, *, write=False):
        if self.database is None:
            raise MemoryAccessError("memory_not_configured", 503)
        if not self.database.is_file():
            raise MemoryAccessError("memory_database_missing", 503)
        if write and not self.allow_delete:
            raise MemoryAccessError("memory_read_only", 403)
        connection = None
        try:
            # mode=ro/rw 都不创建文件；不用 open_database 或 build_application，
            # 因为它们会初始化/迁移。连接在请求工作线程内创建并关闭。
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
    def _service(connection):
        return MemoryManagementService(memory_store=SQLiteMemoryStore(connection),
                                       conversation_store=SQLiteConversationStore(connection))

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

    def get(self, memory_id):
        with self._open() as connection:
            details = self._service(connection).get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            data = details_json(details)
            return {**data, "revision": revision(data)}

    def delete(self, memory_id, expected_revision):
        with self._open(write=True) as connection:
            service = self._service(connection)
            details = service.get_memory(MemoryId(memory_id))
            if details is None:
                raise MemoryAccessError("memory_not_found", 404)
            if not secrets.compare_digest(revision(details_json(details)), expected_revision):
                raise MemoryAccessError("memory_changed")
            # 复用已经测试过的语义：删除 L1 + 来源关联，保留 L0 原始对话。
            # 外键还会解除其他记忆指向此条的取代链接，不冒充完整隐私擦除。
            if not service.delete_memory(MemoryId(memory_id)):
                raise MemoryAccessError("memory_not_found", 404)
            return {"deleted": True, "id": memory_id, "l0_preserved": True}
