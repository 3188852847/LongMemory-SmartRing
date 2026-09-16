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
    BETWEEN_INTERVALS = "between_intervals"


@dataclass(frozen=True, slots=True)
class ScheduledTriggerDecision:
    action: ScheduledTriggerAction
    reason: ScheduledTriggerReason
    local_date: date
    scheduled_for: datetime | None = None
    idempotency_key: str | None = None


def next_interval_anchor_minute(config, *, now: datetime) -> int:
    """短周期从保存后的下一个允许分钟开始，锚点不再由用户管理。"""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("interval_anchor_now_timezone_required")
    local_zone = timezone(timedelta(minutes=config.utc_offset_minutes))
    local_now = now.astimezone(local_zone).replace(second=0, microsecond=0)
    for offset in range(1, 24 * 60 + 1):
        candidate = local_now + timedelta(minutes=offset)
        minute = candidate.hour * 60 + candidate.minute
        start = config.allowed_start_minute
        end = config.allowed_end_minute
        inside = (
            start <= minute < end
            if start < end
            else minute >= start or minute < end
        )
        if inside:
            return minute
    raise ValueError("interval_anchor_allowed_window_empty")


def scheduled_trigger_slot(
    settings: ProactivePolicySettings, *, now: datetime,
) -> tuple[datetime, str] | None:
    """返回当前分钟所属的唯一问候时间槽；其他分钟不产生候选。"""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scheduled_trigger_now_timezone_required")
    local_zone = timezone(timedelta(minutes=settings.config.utc_offset_minutes))
    local_now = now.astimezone(local_zone)
    current_minute = local_now.hour * 60 + local_now.minute
    interval_minutes = settings.automatic_interval_seconds // 60
    local_midnight = datetime.combine(
        local_now.date(), datetime.min.time(), tzinfo=local_zone,
    )
    scheduled_local = local_midnight + timedelta(minutes=current_minute)
    if settings.automatic_interval_seconds == 24 * 60 * 60:
        # 每日模式沿用固定本地钟点，不把前一天的时刻滚动到今天。
        if current_minute != settings.scheduled_minute:
            return None
    else:
        # 短周期使用连续时间轴。否则“每 7 分钟”跨过午夜后会因当天分钟数
        # 重新归零而失去原有相位，甚至要等到当天首个检查时刻才恢复。
        anchor_date = (
            settings.updated_at.astimezone(local_zone).date()
            if settings.updated_at is not None
            else local_now.date()
        )
        if settings.updated_at is not None:
            updated_local = settings.updated_at.astimezone(local_zone)
            updated_minute = updated_local.hour * 60 + updated_local.minute
            if settings.scheduled_minute <= updated_minute:
                anchor_date += timedelta(days=1)
        anchor_local = datetime.combine(
            anchor_date, datetime.min.time(), tzinfo=local_zone,
        ) + timedelta(minutes=settings.scheduled_minute)
        elapsed_minutes = int(
            (scheduled_local - anchor_local).total_seconds() // 60
        )
        if elapsed_minutes < 0 or elapsed_minutes % interval_minutes != 0:
            return None
    scheduled_utc = scheduled_local.astimezone(timezone.utc)
    # 设置在本分钟内刚被保存时，分钟边界早于真实授权时刻；这一槽不能倒推创建。
    # 这也避免“每 1 分钟”语音命令保存后在同一分钟立刻自问一句。
    if settings.updated_at is not None and scheduled_utc < settings.updated_at:
        return None
    key = (
        f"explicit-schedule:{local_now.date().isoformat()}"
        if settings.automatic_interval_seconds == 24 * 60 * 60
        else f"interval-schedule:{scheduled_utc.isoformat(timespec='minutes')}"
    )
    return scheduled_utc, key


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
    slot = scheduled_trigger_slot(settings, now=now)
    if slot is None:
        if current_minute < settings.scheduled_minute:
            return result(ScheduledTriggerAction.WAIT, ScheduledTriggerReason.BEFORE_SCHEDULE)
        if settings.automatic_interval_seconds == 24 * 60 * 60:
            return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.MISSED_SCHEDULE)
        return result(ScheduledTriggerAction.WAIT, ScheduledTriggerReason.BETWEEN_INTERVALS)
    if already_evaluated_today:
        return result(ScheduledTriggerAction.SKIP, ScheduledTriggerReason.ALREADY_EVALUATED_TODAY)
    if user_chatted_today and settings.automatic_interval_seconds == 24 * 60 * 60:
        return result(
            ScheduledTriggerAction.SKIP,
            ScheduledTriggerReason.USER_ALREADY_CHATTED_TODAY,
        )
    scheduled_for, idempotency_key = slot
    return result(
        ScheduledTriggerAction.CREATE,
        ScheduledTriggerReason.READY,
        scheduled_for,
        idempotency_key,
    )
