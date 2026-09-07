"""主动交流的技术中立状态与审计事件。

主动交流不是记忆层级：这里记录系统为什么想联系、实际走到了哪一步，
不能把“用户没有回应”等结果直接写成 L3 用户画像。
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum


class OutreachTrigger(StrEnum):
    MANUAL_TEST = "manual_test"
    EXPLICIT_SCHEDULE = "explicit_schedule"
    INACTIVITY_RULE = "inactivity_rule"
    HABIT_CANDIDATE = "habit_candidate"


class OutreachState(StrEnum):
    CANDIDATE = "candidate"
    BLOCKED = "blocked"
    QUEUED = "queued"
    TRANSPORT_SENT = "transport_sent"
    DEVICE_ACKNOWLEDGED = "device_acknowledged"
    PLAYED = "played"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OutreachEvidence(StrEnum):
    SYSTEM_CREATED = "system_created"
    POLICY_DECISION = "policy_decision"
    SERVER_QUEUE = "server_queue"
    TRANSPORT_WRITE = "transport_write"
    DEVICE_ACK = "device_ack"
    USER_OBSERVED = "user_observed"
    SYSTEM_RECOVERY = "system_recovery"


TERMINAL_STATES = frozenset({
    OutreachState.BLOCKED,
    OutreachState.PLAYED,
    OutreachState.EXPIRED,
    OutreachState.CANCELLED,
    OutreachState.FAILED,
})

ALLOWED_TRANSITIONS = {
    OutreachState.CANDIDATE: frozenset({
        OutreachState.BLOCKED,
        OutreachState.QUEUED,
        OutreachState.EXPIRED,
        OutreachState.CANCELLED,
    }),
    OutreachState.QUEUED: frozenset({
        OutreachState.TRANSPORT_SENT,
        # 当前小智协议不返回逐条播放回执；用户亲耳确认属于更强证据，
        # 可以跳过不可观察的传输中间态，直接形成 played 事实。
        OutreachState.PLAYED,
        OutreachState.EXPIRED,
        OutreachState.CANCELLED,
        OutreachState.FAILED,
    }),
    OutreachState.TRANSPORT_SENT: frozenset({
        OutreachState.DEVICE_ACKNOWLEDGED,
        OutreachState.PLAYED,
        OutreachState.FAILED,
    }),
    OutreachState.DEVICE_ACKNOWLEDGED: frozenset({
        OutreachState.PLAYED,
        OutreachState.FAILED,
    }),
}


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")


def _bounded(value: str, field: str, maximum: int) -> None:
    if value != value.strip() or not value or len(value) > maximum:
        raise ValueError(f"{field}_invalid")


@dataclass(frozen=True, slots=True)
class ProactiveOutreach:
    id: str
    subject_id: str
    trigger: OutreachTrigger
    trigger_reason_code: str
    content: str
    created_at: datetime
    scheduled_for: datetime
    expires_at: datetime
    state: OutreachState = OutreachState.CANDIDATE
    state_changed_at: datetime | None = None
    idempotency_key: str = ""
    policy_version: str | None = None
    topic_seed_id: str | None = None
    topic_seed_revision: int | None = None
    strategy_version_id: str | None = None
    strategy_selection_revision: int | None = None
    strategy_evaluated_local_date: str | None = None
    revision: int = 1
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _bounded(self.id, "outreach_id", 120)
        _bounded(self.subject_id, "outreach_subject", 120)
        _bounded(self.trigger_reason_code, "outreach_trigger_reason", 120)
        _bounded(self.content, "outreach_content", 500)
        _bounded(self.idempotency_key, "outreach_idempotency_key", 160)
        _aware(self.created_at, "outreach_created_at")
        _aware(self.scheduled_for, "outreach_scheduled_for")
        _aware(self.expires_at, "outreach_expires_at")
        changed = self.state_changed_at or self.created_at
        _aware(changed, "outreach_state_changed_at")
        if self.scheduled_for < self.created_at or self.expires_at <= self.scheduled_for:
            raise ValueError("outreach_time_window_invalid")
        if changed < self.created_at:
            raise ValueError("outreach_state_time_invalid")
        if self.revision < 1:
            raise ValueError("outreach_revision_invalid")
        if self.policy_version is not None:
            _bounded(self.policy_version, "outreach_policy_version", 120)
        if (self.topic_seed_id is None) != (self.topic_seed_revision is None):
            raise ValueError("outreach_topic_source_mismatch")
        if self.topic_seed_id is not None:
            _bounded(self.topic_seed_id, "outreach_topic_seed_id", 120)
            if self.topic_seed_revision < 1:
                raise ValueError("outreach_topic_seed_revision_invalid")
        strategy_source = (
            self.strategy_version_id,
            self.strategy_selection_revision,
            self.strategy_evaluated_local_date,
        )
        # 三个字段共同构成一次运行对策略来源的不可歧义绑定；禁止只写一半。
        if any(value is not None for value in strategy_source):
            if any(value is None for value in strategy_source):
                raise ValueError("outreach_strategy_source_mismatch")
            if self.trigger != OutreachTrigger.HABIT_CANDIDATE:
                raise ValueError("outreach_strategy_source_trigger_invalid")
            _bounded(self.strategy_version_id, "outreach_strategy_version_id", 120)
            if self.strategy_selection_revision < 1:
                raise ValueError("outreach_strategy_selection_revision_invalid")
            try:
                parsed_date = date.fromisoformat(self.strategy_evaluated_local_date)
            except ValueError:
                raise ValueError("outreach_strategy_local_date_invalid") from None
            if parsed_date.isoformat() != self.strategy_evaluated_local_date:
                raise ValueError("outreach_strategy_local_date_invalid")
        if (self.state == OutreachState.FAILED) != (self.failure_reason is not None):
            raise ValueError("outreach_failure_reason_mismatch")
        if self.failure_reason is not None:
            _bounded(self.failure_reason, "outreach_failure_reason", 120)


@dataclass(frozen=True, slots=True)
class OutreachEvent:
    id: str
    outreach_id: str
    sequence: int
    previous_state: OutreachState | None
    new_state: OutreachState
    reason_code: str
    evidence: OutreachEvidence
    occurred_at: datetime

    def __post_init__(self) -> None:
        _bounded(self.id, "outreach_event_id", 120)
        _bounded(self.outreach_id, "outreach_event_outreach_id", 120)
        _bounded(self.reason_code, "outreach_event_reason", 120)
        _aware(self.occurred_at, "outreach_event_occurred_at")
        if self.sequence < 1:
            raise ValueError("outreach_event_sequence_invalid")
        if self.sequence == 1:
            if (self.previous_state is not None
                    or self.new_state != OutreachState.CANDIDATE
                    or self.evidence != OutreachEvidence.SYSTEM_CREATED):
                raise ValueError("outreach_initial_event_invalid")
        elif self.previous_state is None:
            raise ValueError("outreach_previous_state_required")


def transition_outreach(
    outreach: ProactiveOutreach,
    *,
    new_state: OutreachState,
    occurred_at: datetime,
    failure_reason: str | None = None,
) -> ProactiveOutreach:
    """只允许单向、可解释的状态变化，不允许用同状态覆盖历史。"""

    _aware(occurred_at, "outreach_transition_at")
    if new_state not in ALLOWED_TRANSITIONS.get(outreach.state, frozenset()):
        raise ValueError("outreach_transition_invalid")
    if occurred_at < (outreach.state_changed_at or outreach.created_at):
        raise ValueError("outreach_transition_time_invalid")
    if new_state == OutreachState.FAILED:
        if failure_reason is None:
            raise ValueError("outreach_failure_reason_required")
    elif failure_reason is not None:
        raise ValueError("outreach_failure_reason_unexpected")
    return replace(
        outreach,
        state=new_state,
        state_changed_at=occurred_at,
        revision=outreach.revision + 1,
        failure_reason=failure_reason,
    )
