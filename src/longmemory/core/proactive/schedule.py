"""显式定时问候的纯触发计划；不访问数据库、模型或设备。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

from .settings import ProactivePolicySettings


class ScheduledTriggerAction(StrEnum):
    CREATE = "create"
    SKIP = "skip"
    WAIT = "wait"


class ScheduledTriggerReason(StrEnum):
    READY = "ready"
    AUTOMATIC_DISABLED = "automatic_disabled"
    CONTACT_DISABLED = "contact_disabled"
    WEEKDAY_NOT_SELECTED = "weekday_not_selected"
    BEFORE_SCHEDULE = "before_schedule"
    MISSED_SCHEDULE = "missed_schedule"
    USER_ALREADY_CHATTED_TODAY = "user_already_chatted_today"
    ALREADY_EVALUATED_TODAY = "already_evaluated_today"


@dataclass(frozen=True, slots=True)
class ScheduledTriggerDecision:
    action: ScheduledTriggerAction
    reason: ScheduledTriggerReason
    local_date: date
    scheduled_for: datetime | None = None
    idempotency_key: str | None = None


def decide_scheduled_trigger(
    settings: ProactivePolicySettings,
    *,
    now: datetime,
    user_chatted_today: bool,
    already_evaluated_today: bool,
) -> ScheduledTriggerDecision:
    """只在配置的当地分钟内创建候选；过了该分钟绝不补发。"""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduled_trigger_now_timezone_required")
    local_zone = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
    local_now = now.astimezone(local_zone)
    local_date = local_now.date()

    def result(action, reason, scheduled_for=None, idempotency_key=None):
        return ScheduledTriggerDecision(
            action, reason, local_date, scheduled_for, idempotency_key,
        )

    if not settings.automatic_enabled:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.AUTOMATIC_DISABLED)
    if not settings.config.enabled:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.CONTACT_DISABLED)
    if local_now.weekday() not in settings.config.allowed_weekdays:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.WEEKDAY_NOT_SELECTED)

    current_minute = local_now.hour * 60 + local_now.minute
    if current_minute < settings.scheduled_minute:
        return result(ScheduledTriggerAction.WAIT, ScheduledTriggerReason.BEFORE_SCHEDULE)
    if current_minute > settings.scheduled_minute:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.MISSED_SCHEDULE)
    if already_evaluated_today:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.ALREADY_EVALUATED_TODAY)
    if user_chatted_today:
        return result(
            ScheduledTriggerAction.SKIP,
            ScheduledTriggerReason.USER_ALREADY_CHATTED_TODAY,
        )

    local_midnight = datetime.combine(local_date, datetime.min.time(), tzinfo=local_zone)
    scheduled_local = local_midnight + timedelta(minutes=settings.scheduled_minute)
    return result(
        ScheduledTriggerAction.CREATE,
        ScheduledTriggerReason.READY,
        scheduled_local.astimezone(timezone.utc),
        f"explicit-schedule:{local_date.isoformat()}",
    )
