"""L2 场景记忆的控制台管理协作者。

该对象只编排 L2 读取、候选生成和生命周期操作。数据库身份与写权限仍由
MemoryBackend 注入的打开函数统一守卫，避免产生第二套安全边界。
"""

from datetime import datetime

from longmemory.adapters.llm.scenario_candidate import SCENARIO_PROMPT_VERSION
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.application.scenario_management.proposal_service import (
    ScenarioProposalService,
)
from longmemory.application.scenario_management.service import ScenarioManagementService
from longmemory.core.common.identifiers import MemoryId, ScenarioId
from longmemory.core.memory.l2_scenario.models import ScenarioReviewDecision
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposalError,
    ScenarioProposalInput,
)

from .errors import MemoryAccessError
from .memory_presenters import scenario_json


class ScenarioBackend:
    def __init__(self, *, open_database, allow_management, producer=None, model=None):
        self._open_database = open_database
        self._allow_management = allow_management
        self._producer = producer
        self._model = model

    def list(self, *, state="all", limit=25, offset=0):
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("scenario_filter_invalid", 400)
        with self._open_database() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM scenario_memories" + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM scenario_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {
                "items": [scenario_json(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def list_source_inbox(self):
        """列出尚未进入当前候选/已接受 L2 的活跃 L1；只读且不判断主题。"""

        with self._open_database() as connection:
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

    def get(self, scenario_id):
        with self._open_database() as connection:
            row = connection.execute(
                "SELECT * FROM scenario_memories WHERE id=?", (scenario_id,)
            ).fetchone()
            if row is None:
                raise MemoryAccessError("scenario_not_found", 404)
            data = scenario_json(row)
            sources = [dict(source) for source in connection.execute(
                "SELECT s.*, a.content AS current_content, a.retired_at "
                "FROM scenario_memory_sources s LEFT JOIN atomic_memories a ON a.id=s.memory_id "
                "WHERE s.scenario_id=? ORDER BY s.linked_at, s.memory_id",
                (scenario_id,),
            ).fetchall()]
            # L2 详情继续完整回溯到 L0，协作者拆分不能降低可审计性。
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
            review = connection.execute(
                "SELECT decision,reviewer_type,reviewed_at,scenario_revision,"
                "policy_version,decision_reason FROM scenario_reviews WHERE scenario_id=?",
                (scenario_id,),
            ).fetchone()
            data["review"] = dict(review) if review is not None else None
            return data

    def preview(self, *, source_memory_ids):
        """读取所选来源后释放数据库，再调用模型生成不落库草稿。"""

        if not self._allow_management:
            raise MemoryAccessError("scenario_management_disabled", 403)
        if self._producer is None:
            raise MemoryAccessError("scenario_model_preview_unavailable", 503)
        with self._open_database() as connection:
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
            proposal = ScenarioProposalService(self._producer).preview(tuple(sources))
        except ScenarioProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "title": proposal.title,
            "summary": proposal.summary,
            "source_memory_ids": [str(value) for value in proposal.source_memory_ids],
            "generator_name": "model_assisted_console",
            "generator_version": SCENARIO_PROMPT_VERSION,
            "model": self._model,
            "persisted": False,
        }

    def create(self, *, title, summary, source_memory_ids, creation_kind="manual",
               valid_from=None, valid_to=None):
        with self._open_database(write_capability="scenario") as connection:
            service = self._service(connection)
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("scenario_valid_time_invalid", 400) from None
                if creation_kind == "model_assisted" and self._producer is None:
                    raise MemoryAccessError("scenario_model_preview_unavailable", 503)
                scenario = service.create_candidate(
                    title=title,
                    summary=summary,
                    source_memory_ids=tuple(MemoryId(value) for value in source_memory_ids),
                    generator_name=(
                        "model_assisted_console"
                        if creation_kind == "model_assisted" else "manual_console"
                    ),
                    generator_version=(
                        SCENARIO_PROMPT_VERSION if creation_kind == "model_assisted" else "1"
                    ),
                    valid_from=parsed_valid_from,
                    valid_to=parsed_valid_to,
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(scenario.id), "status": scenario.status.value}

    def review(self, scenario_id, *, decision, expected_revision):
        with self._open_database(write_capability="scenario") as connection:
            service = self._service(connection)
            try:
                scenario = service.review(
                    ScenarioId(scenario_id),
                    ScenarioReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {
                "reviewed": True,
                "id": scenario_id,
                "status": scenario.status.value,
                "revision": scenario.revision,
            }

    def end(self, scenario_id, *, expected_revision):
        """显式结束 active L2；内容与来源不变，新增生命周期事件。"""

        with self._open_database(write_capability="scenario") as connection:
            service = self._service(connection)
            try:
                scenario = service.end(
                    ScenarioId(scenario_id), expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {
                "ended": True,
                "id": scenario_id,
                "status": scenario.status.value,
                "revision": scenario.revision,
            }

    @staticmethod
    def _service(connection):
        return ScenarioManagementService(
            memory_store=SQLiteMemoryStore(connection, commit_changes=False),
            scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
        )
