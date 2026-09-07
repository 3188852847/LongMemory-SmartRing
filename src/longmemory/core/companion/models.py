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
class UserInitiatedInteractionEvent:
    """长静默后且非主动问候引出的用户消息时间证据。"""

    id: str
    subject_id: str
    source_message_id: str
    occurred_at: datetime
    previous_user_message_at: datetime | None
    silence_gap_seconds: int | None
    evidence_kind: str = "silence_gap_without_recent_outreach"
    detector_version: str = "user-initiated-interaction-v1"

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (
            self.id, self.subject_id, self.source_message_id,
            self.evidence_kind, self.detector_version,
        )):
            raise ValueError("user_initiated_interaction_identity_invalid")
        if self.occurred_at.tzinfo is None:
            raise ValueError("user_initiated_interaction_time_invalid")
        if self.previous_user_message_at is None:
            if self.silence_gap_seconds is not None:
                raise ValueError("user_initiated_interaction_gap_invalid")
        elif (
            self.previous_user_message_at.tzinfo is None
            or self.silence_gap_seconds is None
            or self.silence_gap_seconds < 0
        ):
            raise ValueError("user_initiated_interaction_gap_invalid")


class CompanionStrategyCandidateStatus(StrEnum):
    """策略候选当前只允许等待观察或被所有者忽略。"""

    CANDIDATE = "candidate"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class CompanionRoutineCandidate:
    """由跨日主动出现时间支持的弱习惯假设；本身不触发联系。"""

    id: str
    subject_id: str
    status: CompanionStrategyCandidateStatus
    expected_minute: int
    utc_offset_minutes: int
    observation_window_minutes: int
    evidence_count: int
    distinct_local_dates: int
    evidence_fingerprint: str
    rationale_code: str
    generator_version: str
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (
            self.id, self.subject_id, self.evidence_fingerprint,
            self.rationale_code, self.generator_version,
        )):
            raise ValueError("companion_routine_candidate_identity_invalid")
        if not 0 <= self.expected_minute <= 1439:
            raise ValueError("companion_routine_candidate_minute_invalid")
        if not -720 <= self.utc_offset_minutes <= 840:
            raise ValueError("companion_routine_candidate_offset_invalid")
        if self.observation_window_minutes != 30:
            raise ValueError("companion_routine_candidate_window_invalid")
        if self.evidence_count < 3 or self.distinct_local_dates < 3:
            raise ValueError("companion_routine_candidate_evidence_insufficient")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("companion_routine_candidate_time_invalid")
        if self.revision < 1:
            raise ValueError("companion_routine_candidate_revision_invalid")


@dataclass(frozen=True, slots=True)
class CompanionStrategyObservation:
    """生成候选所需的最小时间证据；不携带对话正文。"""

    interaction_event_id: str
    outreach_id: str
    queued_at: datetime
    observed_at: datetime
    latency_seconds: int
    delivery_evidence_level: str

    def __post_init__(self) -> None:
        if not self.interaction_event_id.strip() or not self.outreach_id.strip():
            raise ValueError("companion_strategy_observation_identity_invalid")
        if self.queued_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("companion_strategy_observation_time_invalid")
        if not 0 <= self.latency_seconds <= 1800:
            raise ValueError("companion_strategy_observation_latency_invalid")
        if self.delivery_evidence_level not in {
            "server_queued", "transport_sent", "device_acknowledged", "played",
        }:
            raise ValueError("companion_strategy_observation_evidence_invalid")


@dataclass(frozen=True, slots=True)
class CompanionStrategyCandidate:
    """尚未生效的陪伴策略假设，不等同于用户画像或偏好。"""

    id: str
    subject_id: str
    status: CompanionStrategyCandidateStatus
    suggested_minute: int
    utc_offset_minutes: int
    evidence_count: int
    distinct_local_dates: int
    evidence_fingerprint: str
    rationale_code: str
    generator_version: str
    created_at: datetime
    updated_at: datetime
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.subject_id.strip():
            raise ValueError("companion_strategy_candidate_identity_invalid")
        if not 0 <= self.suggested_minute <= 1439:
            raise ValueError("companion_strategy_candidate_minute_invalid")
        if not -720 <= self.utc_offset_minutes <= 840:
            raise ValueError("companion_strategy_candidate_offset_invalid")
        if self.evidence_count < 3 or self.distinct_local_dates < 3:
            raise ValueError("companion_strategy_candidate_evidence_insufficient")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("companion_strategy_candidate_time_invalid")
        if self.revision < 1 or any(not value.strip() for value in (
            self.evidence_fingerprint, self.rationale_code, self.generator_version,
        )):
            raise ValueError("companion_strategy_candidate_metadata_invalid")


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
