"""基于日常交流时段的缺席判断；只产生候选，不负责联系用户。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum


class AbsenceTriggerAction(StrEnum):
    CREATE = "create"
    WAIT = "wait"
    SKIP = "skip"


class AbsenceTriggerReason(StrEnum):
    READY = "routine_absence_ready"
    DRAFT_DISABLED = "draft_disabled"
    WEEKDAY_NOT_ALLOWED = "weekday_not_allowed"
    BEFORE_CHECK = "before_absence_check"
    MISSED_CHECK = "missed_absence_check"
    ROUTINE_OBSERVED = "routine_observed_today"
    USER_ALREADY_CHATTED = "user_already_chatted_today"
    ALREADY_EVALUATED = "already_evaluated_today"


@dataclass(frozen=True, slots=True)
class AbsenceRoutineDraft:
    """尚未激活的策略草案；时间均按显式固定 UTC 偏移解释。"""

    candidate_id: str
    expected_minute: int
    grace_minutes: int = 60
    utc_offset_minutes: int = 8 * 60
    allowed_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    enabled: bool = False
    policy_version: str = "routine-absence-trigger-v1"

    def __post_init__(self) -> None:
        # v1 暂不让检查时刻跨日，避免把“哪一天缺席”解释错。
        if (
            not self.candidate_id
            or self.candidate_id != self.candidate_id.strip()
            or len(self.candidate_id) > 120
            or not 0 <= self.expected_minute < 24 * 60
            or not 15 <= self.grace_minutes <= 6 * 60
            or self.expected_minute + self.grace_minutes >= 24 * 60
            or not -12 * 60 <= self.utc_offset_minutes <= 14 * 60
            or not self.allowed_weekdays
            or len(set(self.allowed_weekdays)) != len(self.allowed_weekdays)
            or any(day not in range(7) for day in self.allowed_weekdays)
            or self.policy_version != "routine-absence-trigger-v1"
        ):
            raise ValueError("absence_routine_draft_invalid")


@dataclass(frozen=True, slots=True)
class AbsenceRoutineState:
    """由可信事件汇总，不允许模型自行填写这些布尔状态。"""

    routine_observed_today: bool = False
    user_chatted_today: bool = False
    already_evaluated_today: bool = False


@dataclass(frozen=True, slots=True)
class AbsenceTriggerDecision:
    action: AbsenceTriggerAction
    reason: AbsenceTriggerReason
    local_date: date
    check_at: datetime | None = None
    idempotency_key: str | None = None


def decide_routine_absence(
    draft: AbsenceRoutineDraft,
    *,
    now: datetime,
    state: AbsenceRoutineState,
) -> AbsenceTriggerDecision:
    """在宽限期结束的唯一当地分钟判断一次，错过后绝不补发。"""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("absence_trigger_now_timezone_required")
    local_zone = timezone(timedelta(minutes=draft.utc_offset_minutes))
    local_now = now.astimezone(local_zone)
    local_date = local_now.date()

    def result(action, reason, check_at=None, idempotency_key=None):
        return AbsenceTriggerDecision(action, reason, local_date, check_at, idempotency_key)

    if not draft.enabled:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.DRAFT_DISABLED)
    if local_now.weekday() not in draft.allowed_weekdays:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.WEEKDAY_NOT_ALLOWED)

    check_minute = draft.expected_minute + draft.grace_minutes
    current_minute = local_now.hour * 60 + local_now.minute
    if current_minute < check_minute:
        return result(AbsenceTriggerAction.WAIT, AbsenceTriggerReason.BEFORE_CHECK)
    if current_minute > check_minute:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.MISSED_CHECK)
    if state.already_evaluated_today:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.ALREADY_EVALUATED)
    if state.routine_observed_today:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.ROUTINE_OBSERVED)
    if state.user_chatted_today:
        return result(AbsenceTriggerAction.SKIP, AbsenceTriggerReason.USER_ALREADY_CHATTED)

    local_midnight = datetime.combine(local_date, datetime.min.time(), tzinfo=local_zone)
    check_at = (local_midnight + timedelta(minutes=check_minute)).astimezone(timezone.utc)
    return result(
        AbsenceTriggerAction.CREATE,
        AbsenceTriggerReason.READY,
        check_at,
        f"routine-absence:{draft.candidate_id}:{local_date.isoformat()}",
    )
