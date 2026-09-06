"""L3 用户画像候选、来源快照与人工复核领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from longmemory.core.common.identifiers import (
    MemorySubjectId,
    PersonaAuditId,
    PersonaId,
    PersonaLifecycleEventId,
    PersonaReviewId,
)


class PersonaKind(StrEnum):
    """画像表达的内容类型，而不是模型置信分数。"""

    PREFERENCE = "preference"
    HABIT = "habit"
    INTERACTION_STYLE = "interaction_style"
    BEHAVIOR_PATTERN = "behavior_pattern"


class PersonaBasis(StrEnum):
    """区分用户明确表达与系统跨记录归纳，避免来源角色坍缩。"""

    USER_DECLARED = "user_declared"
    SYSTEM_INFERRED = "system_inferred"


class PersonaStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    STALE = "stale"


class PersonaSourceLayer(StrEnum):
    L1 = "l1"
    L2 = "l2"


class PersonaReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PersonaReviewerType(StrEnum):
    """区分人的判断和确定性策略判断，禁止自动化冒充用户。"""

    USER = "user"
    POLICY = "policy"


class PersonaLifecycleAction(StrEnum):
    SOURCE_RETIRED = "source_retired"
    SOURCE_DELETED = "source_deleted"
    SOURCE_STALE = "source_stale"


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")


@dataclass(frozen=True, slots=True)
class PersonaMemory:
    """一条可独立核对的画像断言；不把整份用户档案塞进一个文本块。"""

    id: PersonaId
    subject_id: MemorySubjectId
    kind: PersonaKind
    basis: PersonaBasis
    label: str
    statement: str
    generated_at: datetime
    status: PersonaStatus
    generator_name: str
    generator_version: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if not 1 <= len(self.label.strip()) <= 120:
            raise ValueError("persona_label_invalid")
        if not 1 <= len(self.statement.strip()) <= 1000:
            raise ValueError("persona_statement_invalid")
        if not self.generator_name.strip() or not self.generator_version.strip():
            raise ValueError("persona_generator_invalid")
        _require_aware(self.generated_at, "generated_at")
        for name, value in (("valid_from", self.valid_from), ("valid_to", self.valid_to)):
            if value is not None:
                _require_aware(value, name)
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("persona_valid_range_invalid")
        if self.revision < 1:
            raise ValueError("persona_revision_invalid")


@dataclass(frozen=True, slots=True)
class PersonaSource:
    persona_id: PersonaId
    source_layer: PersonaSourceLayer
    source_id: str
    source_content_snapshot: str
    linked_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_content_snapshot.strip():
            raise ValueError("persona_source_invalid")
        _require_aware(self.linked_at, "linked_at")


@dataclass(frozen=True, slots=True)
class PersonaGenerationAudit:
    """保存证据覆盖统计；门槛按声明型与推断型分别验证。"""

    id: PersonaAuditId
    persona_id: PersonaId
    basis: PersonaBasis
    generator_name: str
    generator_version: str
    generated_at: datetime
    source_count: int
    source_message_count: int
    observation_day_count: int

    def __post_init__(self) -> None:
        if not self.generator_name.strip() or not self.generator_version.strip():
            raise ValueError("persona_generator_invalid")
        _require_aware(self.generated_at, "generated_at")
        if min(self.source_count, self.source_message_count, self.observation_day_count) < 1:
            raise ValueError("persona_evidence_threshold_not_met")
        # 明确声明可由一条原话支持；系统推断的稳定模式必须跨来源、跨日期。
        if self.basis == PersonaBasis.SYSTEM_INFERRED and (
            self.source_count < 2
            or self.source_message_count < 3
            or self.observation_day_count < 2
        ):
            raise ValueError("persona_inference_evidence_threshold_not_met")


@dataclass(frozen=True, slots=True)
class PersonaReview:
    id: PersonaReviewId
    persona_id: PersonaId
    decision: PersonaReviewDecision
    reviewed_at: datetime
    persona_revision: int
    reviewer_type: PersonaReviewerType = PersonaReviewerType.USER
    policy_version: str | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.reviewed_at, "reviewed_at")
        if self.persona_revision < 1:
            raise ValueError("persona_revision_invalid")
        if self.reviewer_type == PersonaReviewerType.USER:
            if self.policy_version is not None or self.decision_reason is not None:
                raise ValueError("persona_user_review_policy_metadata_forbidden")
            return
        if self.decision != PersonaReviewDecision.ACCEPTED:
            raise ValueError("persona_policy_review_must_accept")
        if (
            self.policy_version is None
            or self.decision_reason is None
            or not 1 <= len(self.policy_version.strip()) <= 120
            or not 1 <= len(self.decision_reason.strip()) <= 120
        ):
            raise ValueError("persona_policy_review_metadata_required")


@dataclass(frozen=True, slots=True)
class PersonaReplacement:
    """候选拟取代的旧画像；接受候选前仅是可审计意图。"""

    candidate_persona_id: PersonaId
    replaced_persona_id: PersonaId
    target_revision: int
    linked_at: datetime
    applied_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.candidate_persona_id == self.replaced_persona_id:
            raise ValueError("persona_replacement_self_reference")
        if self.target_revision < 1:
            raise ValueError("persona_revision_invalid")
        _require_aware(self.linked_at, "linked_at")
        if self.applied_at is not None:
            _require_aware(self.applied_at, "applied_at")


@dataclass(frozen=True, slots=True)
class PersonaResolvedSource:
    """已向下解析到用户 L0 的来源；只用于创建前资格核对。"""

    source_layer: PersonaSourceLayer
    source_id: str
    subject_id: MemorySubjectId
    content_snapshot: str
    user_message_ids: tuple[str, ...]
    observation_days: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonaLifecycleEvent:
    id: PersonaLifecycleEventId
    persona_id: PersonaId
    action: PersonaLifecycleAction
    source_layer: PersonaSourceLayer
    source_id: str
    occurred_at: datetime
    previous_status: PersonaStatus
    new_status: PersonaStatus
    persona_revision: int

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("persona_source_invalid")
        _require_aware(self.occurred_at, "occurred_at")
        if self.previous_status not in {PersonaStatus.CANDIDATE, PersonaStatus.ACTIVE}:
            raise ValueError("persona_lifecycle_previous_status_invalid")
        if self.new_status != PersonaStatus.STALE or self.persona_revision < 2:
            raise ValueError("persona_lifecycle_target_invalid")
