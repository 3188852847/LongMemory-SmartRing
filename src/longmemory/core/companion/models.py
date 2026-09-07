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
