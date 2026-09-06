"""L2 时间化场景候选、来源快照和人工复核领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from longmemory.core.common.identifiers import (
    MemoryId,
    MemorySubjectId,
    ScenarioAuditId,
    ScenarioId,
    ScenarioReviewId,
    ScenarioLifecycleEventId,
)


class ScenarioStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    STALE = "stale"


class ScenarioReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ScenarioLifecycleAction(StrEnum):
    MANUAL_END = "manual_end"
    SOURCE_RETIRED = "source_retired"
    SOURCE_DELETED = "source_deleted"


class ScenarioLifecycleActor(StrEnum):
    USER = "user"
    SYSTEM = "system"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")


@dataclass(frozen=True, slots=True)
class ScenarioMemory:
    id: ScenarioId
    subject_id: MemorySubjectId
    title: str
    summary: str
    generated_at: datetime
    status: ScenarioStatus
    generator_name: str
    generator_version: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if not 1 <= len(self.title.strip()) <= 120:
            raise ValueError("scenario_title_invalid")
        if not 1 <= len(self.summary.strip()) <= 2000:
            raise ValueError("scenario_summary_invalid")
        if not self.generator_name.strip() or not self.generator_version.strip():
            raise ValueError("scenario_generator_invalid")
        _require_aware(self.generated_at, "generated_at")
        for name, value in (("valid_from", self.valid_from), ("valid_to", self.valid_to)):
            if value is not None:
                _require_aware(value, name)
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("scenario_valid_range_invalid")
        if self.revision < 1:
            raise ValueError("scenario_revision_invalid")


@dataclass(frozen=True, slots=True)
class ScenarioSource:
    scenario_id: ScenarioId
    memory_id: MemoryId
    memory_content_snapshot: str
    linked_at: datetime

    def __post_init__(self) -> None:
        if not self.memory_content_snapshot.strip():
            raise ValueError("scenario_source_snapshot_empty")
        _require_aware(self.linked_at, "linked_at")


@dataclass(frozen=True, slots=True)
class ScenarioGenerationAudit:
    id: ScenarioAuditId
    scenario_id: ScenarioId
    generator_name: str
    generator_version: str
    generated_at: datetime
    source_memory_count: int
    source_message_count: int

    def __post_init__(self) -> None:
        if self.source_memory_count < 2 or self.source_message_count < 2:
            raise ValueError("scenario_evidence_threshold_not_met")
        _require_aware(self.generated_at, "generated_at")


@dataclass(frozen=True, slots=True)
class ScenarioReview:
    id: ScenarioReviewId
    scenario_id: ScenarioId
    decision: ScenarioReviewDecision
    reviewed_at: datetime
    scenario_revision: int

    def __post_init__(self) -> None:
        _require_aware(self.reviewed_at, "reviewed_at")
        if self.scenario_revision < 1:
            raise ValueError("scenario_revision_invalid")


@dataclass(frozen=True, slots=True)
class ScenarioLifecycleEvent:
    id: ScenarioLifecycleEventId
    scenario_id: ScenarioId
    action: ScenarioLifecycleAction
    actor_type: ScenarioLifecycleActor
    occurred_at: datetime
    previous_status: ScenarioStatus
    new_status: ScenarioStatus
    scenario_revision: int

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")
        if self.scenario_revision < 2:
            raise ValueError("scenario_revision_invalid")
        if self.new_status != ScenarioStatus.STALE:
            raise ValueError("scenario_lifecycle_target_invalid")
