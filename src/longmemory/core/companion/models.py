"""陪伴互动结果的最小领域模型。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InteractionOutcomeKind(StrEnum):
    """只表达能被记录证明的事件，不表达“效果好”。"""

    SUBSEQUENT_USER_MESSAGE_OBSERVED = "subsequent_user_message_observed"


class InteractionOutcomeEvidence(StrEnum):
    """当前只能证明时间先后，不能证明因果关系。"""

    TEMPORAL_ORDER = "temporal_order"


@dataclass(frozen=True, slots=True)
class InteractionOutcomeEvent:
    id: str
    subject_id: str
    kind: InteractionOutcomeKind
    outreach_id: str
    source_message_id: str
    occurred_at: datetime
    latency_seconds: int
    evidence: InteractionOutcomeEvidence
    recorder_version: str

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.subject_id.strip():
            raise ValueError("interaction_outcome_identity_invalid")
        if not self.outreach_id.strip() or not self.source_message_id.strip():
            raise ValueError("interaction_outcome_source_invalid")
        if self.occurred_at.tzinfo is None or self.latency_seconds < 0:
            raise ValueError("interaction_outcome_time_invalid")
        if not self.recorder_version.strip():
            raise ValueError("interaction_outcome_recorder_invalid")


@dataclass(frozen=True, slots=True)
class ProactiveTopicFeedbackTarget:
    outreach_id: str
    topic_seed_id: str
    topic_seed_revision: int

    def __post_init__(self) -> None:
        if not self.outreach_id.strip() or not self.topic_seed_id.strip():
            raise ValueError("companion_feedback_target_invalid")
        if self.topic_seed_revision < 1:
            raise ValueError("companion_feedback_target_revision_invalid")


@dataclass(frozen=True, slots=True)
class CompanionFeedbackEvent:
    id: str
    subject_id: str
    outreach_id: str
    topic_seed_id: str
    source_message_id: str
    occurred_at: datetime
    feedback_kind: str = "reject_topic"
    action_kind: str = "topic_seed_disabled"
    evidence_kind: str = "user_explicit"
    interpreter_version: str = "explicit-topic-rejection-v1"

    def __post_init__(self) -> None:
        identities = (
            self.id, self.subject_id, self.outreach_id,
            self.topic_seed_id, self.source_message_id,
        )
        if any(not value.strip() for value in identities):
            raise ValueError("companion_feedback_identity_invalid")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("companion_feedback_time_invalid")
        if (
            self.feedback_kind != "reject_topic"
            or self.action_kind != "topic_seed_disabled"
            or self.evidence_kind != "user_explicit"
            or not self.interpreter_version.strip()
        ):
            raise ValueError("companion_feedback_semantics_invalid")
