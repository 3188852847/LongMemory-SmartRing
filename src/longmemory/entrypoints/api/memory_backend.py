"""网页记忆管理的装配边界：只打开显式指定的已有数据库，不运行建库/迁移。"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.application.memory_management.service import MemoryManagementService
from longmemory.application.scenario_management.service import ScenarioManagementService
from longmemory.application.scenario_management.proposal_service import ScenarioProposalService
from longmemory.application.persona_management.service import PersonaManagementService
from longmemory.application.persona_management.proposal_service import PersonaProposalService
from longmemory.application.persona_management.profile import build_persona_profile
from longmemory.core.common.identifiers import MemoryId, PersonaId, ScenarioId
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID
from longmemory.core.memory.l2_scenario.models import ScenarioReviewDecision
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposalError,
    ScenarioProposalInput,
)
from longmemory.adapters.llm.scenario_candidate import SCENARIO_PROMPT_VERSION
from longmemory.adapters.llm.persona_candidate import PERSONA_PROMPT_VERSION
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaReviewDecision,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)
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
    def __init__(self, database: Path | None, *, allow_delete=False, allow_correction=False,
                 allow_scenario_management=False, allow_persona_management=False,
                 scenario_producer=None,
                 scenario_model=None, persona_producer=None, persona_model=None):
        # 路径只来自启动参数；任何 HTTP 请求都不能选文件或切换数据库。
        self.database = database.resolve() if database is not None else None
        self.allow_delete = allow_delete
        self.allow_correction = allow_correction
        self.allow_scenario_management = allow_scenario_management
        self.allow_persona_management = allow_persona_management
        self.scenario_producer = scenario_producer
        self.scenario_model = scenario_model
        self.persona_producer = persona_producer
        self.persona_model = persona_model

    def info(self):
        return {"configured": self.database is not None,
                "database": str(self.database) if self.database else None,
                "allow_delete": self.allow_delete and self.database is not None,
                "allow_correction": self.allow_correction and self.database is not None,
                # 当前两个操作共用同一个显式启动权限，但对前端公开独立能力名，
                # 以后拆分权限时不需要再改变页面语义。
                "allow_change": self.allow_correction and self.database is not None,
                "allow_scenario_management": (
                    self.allow_scenario_management and self.database is not None
                ),
                "allow_persona_management": (
                    self.allow_persona_management and self.database is not None
                ),
                "scenario_model_preview_available": (
                    self.allow_scenario_management
                    and self.database is not None
                    and self.scenario_producer is not None
                ),
                "scenario_model": self.scenario_model if self.scenario_producer else None,
                "persona_model_preview_available": (
                    self.allow_persona_management
                    and self.database is not None
                    and self.persona_producer is not None
                ),
                "persona_model": self.persona_model if self.persona_producer else None}

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
        if write_capability == "scenario" and not self.allow_scenario_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if write_capability == "persona" and not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
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

    def list_scenarios(self, *, state="all", limit=25, offset=0):
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("scenario_filter_invalid", 400)
        with self._open() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM scenario_memories" + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM scenario_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {"items": [self._scenario_json(row) for row in rows],
                    "total": total, "limit": limit, "offset": offset}

    def list_scenario_source_inbox(self):
        """列出尚未进入当前候选/已接受 L2 的活跃 L1；只读且不判断主题。"""

        with self._open() as connection:
            rows = connection.execute(
                "SELECT a.id, a.subject_id, a.content, a.recorded_at, "
                "count(DISTINCT e.source_message_id) AS source_message_count "
                "FROM atomic_memories a "
                "JOIN memory_evidence e ON e.memory_id=a.id "
                "JOIN conversation_messages m ON m.id=e.source_message_id AND m.role='user' "
                "WHERE a.retired_at IS NULL AND NOT EXISTS ("
                "SELECT 1 FROM scenario_memory_sources s "
                "JOIN scenario_memories l2 ON l2.id=s.scenario_id "
                "WHERE s.memory_id=a.id AND l2.status IN ('candidate','active')) "
                "GROUP BY a.id ORDER BY a.recorded_at DESC, a.id DESC LIMIT 100"
            ).fetchall()
            return {
                "items": [dict(row) for row in rows],
                "total": len(rows),
                "limited": len(rows) == 100,
                "selection_is_semantic": False,
            }

    def get_scenario(self, scenario_id):
        with self._open() as connection:
            row = connection.execute(
                "SELECT * FROM scenario_memories WHERE id=?", (scenario_id,)
            ).fetchone()
            if row is None:
                raise MemoryAccessError("scenario_not_found", 404)
            data = self._scenario_json(row)
            sources = [dict(source) for source in connection.execute(
                "SELECT s.*, a.content AS current_content, a.retired_at "
                "FROM scenario_memory_sources s LEFT JOIN atomic_memories a ON a.id=s.memory_id "
                "WHERE s.scenario_id=? ORDER BY s.linked_at, s.memory_id",
                (scenario_id,),
            ).fetchall()]
            # L2 详情必须能沿 L1 继续回到 L0 原话；否则“来源快照”仍只是
            # 另一个派生结论，用户无法判断场景总结有没有超出原始证据。
            for source in sources:
                source["l0_sources"] = [dict(item) for item in connection.execute(
                    "SELECT e.source_message_id, e.source_type, e.linked_at, "
                    "m.role, m.content, m.created_at FROM memory_evidence e "
                    "LEFT JOIN conversation_messages m ON m.id=e.source_message_id "
                    "WHERE e.memory_id=? ORDER BY e.linked_at, e.source_message_id",
                    (source["memory_id"],),
                ).fetchall()]
            data["sources"] = sources
            data["lifecycle_events"] = [dict(event) for event in connection.execute(
                "SELECT id, action, actor_type, occurred_at, previous_status, "
                "new_status, scenario_revision FROM scenario_lifecycle_events "
                "WHERE scenario_id=? ORDER BY occurred_at, id",
                (scenario_id,),
            ).fetchall()]
            return data

    def preview_scenario(self, *, source_memory_ids):
        """读取所选来源后释放数据库，再调用模型生成不落库草稿。"""

        if not self.allow_scenario_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if self.scenario_producer is None:
            raise MemoryAccessError("scenario_model_preview_unavailable", 503)
        with self._open() as connection:
            store = SQLiteMemoryStore(connection)
            sources = []
            for value in source_memory_ids:
                memory = store.get(MemoryId(value))
                if memory is None:
                    raise MemoryAccessError("scenario_source_l1_missing", 400)
                if memory.retired_at is not None:
                    raise MemoryAccessError("scenario_source_l1_retired", 400)
                sources.append(ScenarioProposalInput(
                    memory.id,
                    memory.subject_id,
                    memory.content,
                    tuple(str(item.source_message_id) for item in store.list_evidence(memory.id)),
                ))
        try:
            proposal = ScenarioProposalService(self.scenario_producer).preview(tuple(sources))
        except ScenarioProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "title": proposal.title,
            "summary": proposal.summary,
            "source_memory_ids": [str(value) for value in proposal.source_memory_ids],
            "generator_name": "model_assisted_console",
            "generator_version": SCENARIO_PROMPT_VERSION,
            "model": self.scenario_model,
            "persisted": False,
        }

    def create_scenario(self, *, title, summary, source_memory_ids, creation_kind="manual",
                        valid_from=None, valid_to=None):
        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("scenario_valid_time_invalid", 400) from None
                if creation_kind == "model_assisted" and self.scenario_producer is None:
                    raise MemoryAccessError("scenario_model_preview_unavailable", 503)
                generator_name = (
                    "model_assisted_console" if creation_kind == "model_assisted"
                    else "manual_console"
                )
                generator_version = (
                    SCENARIO_PROMPT_VERSION if creation_kind == "model_assisted" else "1"
                )
                scenario = service.create_candidate(
                    title=title,
                    summary=summary,
                    source_memory_ids=tuple(MemoryId(value) for value in source_memory_ids),
                    generator_name=generator_name,
                    generator_version=generator_version,
                    valid_from=parsed_valid_from,
                    valid_to=parsed_valid_to,
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(scenario.id), "status": scenario.status.value}

    def review_scenario(self, scenario_id, *, decision, expected_revision):
        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                scenario = service.review(
                    ScenarioId(scenario_id), ScenarioReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"reviewed": True, "id": scenario_id,
                    "status": scenario.status.value, "revision": scenario.revision}

    def end_scenario(self, scenario_id, *, expected_revision):
        """显式结束 active L2；内容与来源不变，新增生命周期事件。"""

        with self._open(write_capability="scenario") as connection:
            service = ScenarioManagementService(
                memory_store=SQLiteMemoryStore(connection, commit_changes=False),
                scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
            )
            try:
                scenario = service.end(
                    ScenarioId(scenario_id), expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"ended": True, "id": scenario_id,
                    "status": scenario.status.value, "revision": scenario.revision}

    def list_personas(self, *, state="all", limit=25, offset=0):
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("persona_filter_invalid", 400)
        with self._open() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM persona_memories" + where, parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM persona_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {"items": [self._persona_json(row) for row in rows],
                    "total": total, "limit": limit, "offset": offset}

    def get_persona_profile(self):
        """构造一份用户可见画像；底层原子断言和来源链保持不变。"""

        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            profile = build_persona_profile(
                CURRENT_USER_SUBJECT_ID,
                store.list_active(CURRENT_USER_SUBJECT_ID),
            )
            counts = {status: 0 for status in ("candidate", "active", "rejected", "stale")}
            for row in connection.execute(
                "SELECT status, count(*) AS amount FROM persona_memories "
                "WHERE subject_id=? GROUP BY status",
                (str(CURRENT_USER_SUBJECT_ID),),
            ).fetchall():
                counts[row["status"]] = row["amount"]
            return {
                "subject_id": str(profile.subject_id),
                "representation": "aggregated_active_assertions_v1",
                "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
                "active_assertion_count": profile.assertion_count,
                "status_counts": counts,
                "sections": [{
                    "kind": section.kind.value,
                    "items": [self._persona_model_json(item) for item in section.assertions],
                } for section in profile.sections],
            }

    def list_persona_source_options(self):
        """只返回当前有效的 L1 和已接受 L2；不自动判断适合哪个画像。"""

        with self._open() as connection:
            l1_rows = connection.execute(
                "SELECT id, subject_id, content, recorded_at FROM atomic_memories "
                "WHERE retired_at IS NULL ORDER BY recorded_at DESC, id DESC LIMIT 100"
            ).fetchall()
            l2_rows = connection.execute(
                "SELECT id, subject_id, title, summary, generated_at FROM scenario_memories "
                "WHERE status='active' ORDER BY generated_at DESC, id DESC LIMIT 100"
            ).fetchall()
            return {
                "l1": [{"layer": "l1", "id": row["id"], "subject_id": row["subject_id"],
                        "content": row["content"], "recorded_at": row["recorded_at"]}
                       for row in l1_rows],
                "l2": [{"layer": "l2", "id": row["id"], "subject_id": row["subject_id"],
                        "content": f'{row["title"]}：{row["summary"]}',
                        "recorded_at": row["generated_at"]} for row in l2_rows],
                "selection_is_semantic": False,
            }

    def get_persona(self, persona_id):
        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            persona = store.get(PersonaId(persona_id))
            if persona is None:
                raise MemoryAccessError("persona_not_found", 404)
            data = self._persona_model_json(persona)
            audit = connection.execute(
                "SELECT source_count, source_message_count, observation_day_count "
                "FROM persona_generation_audits WHERE persona_id=?", (persona_id,),
            ).fetchone()
            data["audit"] = dict(audit) if audit is not None else None
            sources = []
            for source in store.list_sources(PersonaId(persona_id)):
                resolved = store.resolve_source(source.source_layer, source.source_id)
                messages = []
                if source.source_layer == PersonaSourceLayer.L1:
                    messages = [dict(row) for row in connection.execute(
                        "SELECT m.id, m.content, m.created_at, e.source_type FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                        (source.source_id,),
                    ).fetchall()]
                else:
                    messages = [dict(row) for row in connection.execute(
                        "SELECT DISTINCT m.id, m.content, m.created_at, e.source_type "
                        "FROM scenario_memory_sources s JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                        (source.source_id,),
                    ).fetchall()]
                sources.append({
                    "source_layer": source.source_layer.value,
                    "source_id": source.source_id,
                    "source_content_snapshot": source.source_content_snapshot,
                    "linked_at": source.linked_at.isoformat(),
                    "current_content": resolved.content_snapshot if resolved else None,
                    "active": resolved is not None,
                    "l0_sources": messages,
                })
            data["sources"] = sources
            data["lifecycle_events"] = [{
                "id": str(event.id), "action": event.action.value,
                "source_layer": event.source_layer.value, "source_id": event.source_id,
                "occurred_at": event.occurred_at.isoformat(),
                "previous_status": event.previous_status.value,
                "new_status": event.new_status.value,
                "persona_revision": event.persona_revision,
            } for event in store.list_lifecycle_events(PersonaId(persona_id))]
            return data

    def create_persona(self, *, kind, basis, label, statement, sources,
                       valid_from=None, valid_to=None, creation_kind="manual"):
        with self._open(write_capability="persona") as connection:
            store = SQLitePersonaStore(connection, commit_changes=False)
            service = PersonaManagementService(persona_store=store)
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("persona_valid_time_invalid", 400) from None
                if creation_kind == "model_assisted" and self.persona_producer is None:
                    raise MemoryAccessError("persona_model_preview_unavailable", 503)
                persona = service.create_candidate(
                    kind=PersonaKind(kind), basis=PersonaBasis(basis), label=label,
                    statement=statement,
                    source_refs=tuple((PersonaSourceLayer(item["layer"]), item["id"])
                                      for item in sources),
                    generator_name=(
                        "model_assisted_console" if creation_kind == "model_assisted"
                        else "manual_console"
                    ),
                    generator_version=(
                        PERSONA_PROMPT_VERSION if creation_kind == "model_assisted" else "1"
                    ),
                    valid_from=parsed_valid_from, valid_to=parsed_valid_to,
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(persona.id), "status": persona.status.value}

    def preview_persona(self, *, basis, sources):
        """读取白名单来源和用户 L0 后关闭数据库，再发起一次模型预览。"""

        if not self.allow_persona_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        if self.persona_producer is None:
            raise MemoryAccessError("persona_model_preview_unavailable", 503)
        try:
            parsed_basis = PersonaBasis(basis)
        except ValueError:
            raise MemoryAccessError("persona_basis_invalid", 400) from None
        inputs = []
        with self._open() as connection:
            store = SQLitePersonaStore(connection)
            for item in sources:
                layer = PersonaSourceLayer(item["layer"])
                resolved = store.resolve_source(layer, item["id"])
                if resolved is None:
                    raise MemoryAccessError("persona_source_missing_or_inactive", 400)
                if layer == PersonaSourceLayer.L1:
                    rows = connection.execute(
                        "SELECT m.id, m.content, m.created_at FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT DISTINCT m.id,m.content,m.created_at FROM scenario_memory_sources s "
                        "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at,m.id",
                        (item["id"],),
                    ).fetchall()
                evidence = tuple(PersonaProposalEvidence(
                    row["id"], row["content"],
                    datetime.fromisoformat(row["created_at"]).astimezone(UTC).date().isoformat(),
                ) for row in rows)
                inputs.append(PersonaProposalInput(
                    layer, item["id"], resolved.subject_id,
                    resolved.content_snapshot, evidence,
                ))
        try:
            proposal = PersonaProposalService(self.persona_producer).preview(
                basis=parsed_basis, sources=tuple(inputs),
            )
        except PersonaProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "kind": proposal.kind.value,
            "basis": proposal.basis.value,
            "label": proposal.label,
            "statement": proposal.statement,
            "sources": [{"layer": layer.value, "id": source_id}
                        for layer, source_id in proposal.source_refs],
            "generator_name": "model_assisted_console",
            "generator_version": PERSONA_PROMPT_VERSION,
            "model": self.persona_model,
            "persisted": False,
        }

    def review_persona(self, persona_id, *, decision, expected_revision):
        with self._open(write_capability="persona") as connection:
            service = PersonaManagementService(
                persona_store=SQLitePersonaStore(connection, commit_changes=False),
            )
            try:
                persona = service.review(
                    PersonaId(persona_id), PersonaReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {"reviewed": True, "id": persona_id,
                    "status": persona.status.value, "revision": persona.revision}

    @staticmethod
    def _scenario_json(row):
        return {key: row[key] for key in (
            "id", "subject_id", "title", "summary", "generated_at", "valid_from",
            "valid_to", "status", "generator_name", "generator_version", "revision",
        )}

    @staticmethod
    def _persona_json(row):
        return {key: row[key] for key in (
            "id", "subject_id", "kind", "basis", "label", "statement",
            "generated_at", "valid_from", "valid_to", "status",
            "generator_name", "generator_version", "revision",
        )}

    @staticmethod
    def _persona_model_json(persona):
        return {
            "id": str(persona.id), "subject_id": str(persona.subject_id),
            "kind": persona.kind.value, "basis": persona.basis.value,
            "label": persona.label, "statement": persona.statement,
            "generated_at": persona.generated_at.isoformat(),
            "valid_from": persona.valid_from.isoformat() if persona.valid_from else None,
            "valid_to": persona.valid_to.isoformat() if persona.valid_to else None,
            "status": persona.status.value, "generator_name": persona.generator_name,
            "generator_version": persona.generator_version, "revision": persona.revision,
        }
