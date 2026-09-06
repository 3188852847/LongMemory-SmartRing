"""编排 L1 来源到 L2 候选；不调用模型、不注入回答。"""

from datetime import UTC, datetime
from uuid import uuid4

from longmemory.core.common.identifiers import (
    MemoryId,
    ScenarioAuditId,
    ScenarioId,
    ScenarioReviewId,
)
from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.l2_scenario.contracts import ScenarioStore
from longmemory.core.memory.l2_scenario.models import (
    ScenarioGenerationAudit,
    ScenarioMemory,
    ScenarioReview,
    ScenarioReviewDecision,
    ScenarioSource,
    ScenarioStatus,
)


class ScenarioManagementService:
    """统一候选和复核入口，避免网页或模型适配器直接操作数据库。"""

    def __init__(self, *, memory_store: MemoryStore, scenario_store: ScenarioStore) -> None:
        self._memory_store = memory_store
        self._scenario_store = scenario_store

    def create_candidate(
        self,
        *,
        title: str,
        summary: str,
        source_memory_ids: tuple[MemoryId, ...],
        generator_name: str,
        generator_version: str,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        generated_at: datetime | None = None,
    ) -> ScenarioMemory:
        """把已经形成的候选和可核对来源作为一个原子操作保存。"""

        if len(set(source_memory_ids)) < 2 or len(set(source_memory_ids)) != len(source_memory_ids):
            raise ValueError("scenario_requires_distinct_l1_sources")
        memories = tuple(self._memory_store.get(memory_id) for memory_id in source_memory_ids)
        if any(memory is None for memory in memories):
            raise LookupError("scenario_source_l1_missing")
        if any(memory.retired_at is not None for memory in memories):
            raise ValueError("scenario_source_l1_retired")
        subjects = {memory.subject_id for memory in memories}
        if len(subjects) != 1:
            raise ValueError("scenario_source_subject_mismatch")

        when = generated_at or datetime.now(UTC)
        scenario_id = ScenarioId(str(uuid4()))
        scenario = ScenarioMemory(
            scenario_id, subjects.pop(), title, summary, when,
            ScenarioStatus.CANDIDATE, generator_name, generator_version,
            valid_from, valid_to,
        )
        sources = tuple(ScenarioSource(
            scenario_id, memory.id, memory.content, when
        ) for memory in memories)
        source_messages = {
            evidence.source_message_id
            for memory in memories
            for evidence in self._memory_store.list_evidence(memory.id)
        }
        audit = ScenarioGenerationAudit(
            ScenarioAuditId(str(uuid4())), scenario_id,
            generator_name, generator_version, when,
            len(memories), len(source_messages),
        )
        self._scenario_store.save_candidate(scenario, sources, audit)
        return scenario

    def review(
        self,
        scenario_id: ScenarioId,
        decision: ScenarioReviewDecision,
        *,
        expected_revision: int,
        reviewed_at: datetime | None = None,
    ) -> ScenarioMemory:
        """记录用户接受或拒绝；过期页面 revision 会被存储层拒绝。"""

        review = ScenarioReview(
            ScenarioReviewId(str(uuid4())), scenario_id, decision,
            reviewed_at or datetime.now(UTC), expected_revision,
        )
        return self._scenario_store.review(review, expected_revision=expected_revision)
