"""主动联系的确定性许可策略；不访问记忆、数据库、模型或设备。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .models import ProactiveOutreach


class OutreachPolicyAction(StrEnum):
    ALLOW = "allow"
    WAIT = "wait"
    BLOCK = "block"


class OutreachPolicyReason(StrEnum):
    READY = "ready"
    NOT_DUE = "not_due"
    DISABLED = "disabled"
    EXPIRED = "expired"
    WINDOW_TOO_LONG = "window_too_long"
    QUIET_PERIOD = "quiet_period"
    WEEKDAY_NOT_ALLOWED = "weekday_not_allowed"
    OUTSIDE_ALLOWED_WINDOW = "outside_allowed_window"
    USER_SESSION_ACTIVE = "user_session_active"
    AWAITING_USER_RESPONSE = "awaiting_user_response"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    MINIMUM_INTERVAL_ACTIVE = "minimum_interval_active"


@dataclass(frozen=True, slots=True)
class OutreachPolicyConfig:
    """用户可控护栏；时间窗口用显式固定 UTC 偏移解释。

    当前产品是中国单用户本机部署，固定偏移避免为 P4.3 新增时区依赖。
    将来需要夏令时或旅行自动切换时，应由配置适配层提供当地时间，不能
    静默猜测。允许时段以分钟表示，开始包含、结束不包含，并支持跨午夜。
    """

    enabled: bool = False
    utc_offset_minutes: int = 8 * 60
    allowed_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    allowed_start_minute: int = 9 * 60
    allowed_end_minute: int = 21 * 60
    daily_limit: int = 1
    minimum_interval: timedelta = timedelta(hours=6)
    maximum_lifetime: timedelta = timedelta(minutes=5)
    policy_version: str = "proactive-contact-policy-v1"

    def __post_init__(self) -> None:
        if (
            not -12 * 60 <= self.utc_offset_minutes <= 14 * 60
            or not self.allowed_weekdays
            or len(set(self.allowed_weekdays)) != len(self.allowed_weekdays)
            or any(day not in range(7) for day in self.allowed_weekdays)
            or not 0 <= self.allowed_start_minute < 24 * 60
            or not 0 <= self.allowed_end_minute < 24 * 60
            or self.allowed_start_minute == self.allowed_end_minute
            or not 1 <= self.daily_limit <= 20
            or not timedelta(0) <= self.minimum_interval <= timedelta(days=7)
            or not timedelta(seconds=5) <= self.maximum_lifetime <= timedelta(minutes=30)
            or self.policy_version != self.policy_version.strip()
            or not 1 <= len(self.policy_version) <= 120
        ):
            raise ValueError("outreach_policy_config_invalid")


@dataclass(frozen=True, slots=True)
class OutreachPolicyState:
    """由应用层从可靠运行状态和 `queued` 事件汇总，不由模型填写。"""

    attempted_at: tuple[datetime, ...] = ()
    awaiting_user_response: bool = False
    user_session_active: bool = False
    quiet_until: datetime | None = None

    def __post_init__(self) -> None:
        for value in self.attempted_at:
            _require_aware(value, "outreach_attempted_at")
        if self.quiet_until is not None:
            _require_aware(self.quiet_until, "outreach_quiet_until")


@dataclass(frozen=True, slots=True)
class OutreachPolicyDecision:
    action: OutreachPolicyAction
    reason: OutreachPolicyReason
    policy_version: str
    next_eligible_at: datetime | None = None


def decide_outreach(
    outreach: ProactiveOutreach,
    *,
    now: datetime,
    state: OutreachPolicyState,
    config: OutreachPolicyConfig = OutreachPolicyConfig(),
) -> OutreachPolicyDecision:
    """判断一个候选现在能否联系；BLOCK 表示本候选不应延后补播。"""

    _require_aware(now, "outreach_policy_now")
    for attempted_at in state.attempted_at:
        if attempted_at > now:
            raise ValueError("outreach_attempt_in_future")

    def decision(
        action: OutreachPolicyAction,
        reason: OutreachPolicyReason,
        next_eligible_at: datetime | None = None,
    ) -> OutreachPolicyDecision:
        return OutreachPolicyDecision(
            action, reason, config.policy_version, next_eligible_at,
        )

    if not config.enabled:
        return decision(OutreachPolicyAction.BLOCK, OutreachPolicyReason.DISABLED)
    if now < outreach.scheduled_for:
        return decision(
            OutreachPolicyAction.WAIT,
            OutreachPolicyReason.NOT_DUE,
            outreach.scheduled_for,
        )
    if now >= outreach.expires_at:
        return decision(OutreachPolicyAction.BLOCK, OutreachPolicyReason.EXPIRED)
    if outreach.expires_at - outreach.scheduled_for > config.maximum_lifetime:
        return decision(OutreachPolicyAction.BLOCK, OutreachPolicyReason.WINDOW_TOO_LONG)
    if state.quiet_until is not None and now < state.quiet_until:
        return decision(OutreachPolicyAction.BLOCK, OutreachPolicyReason.QUIET_PERIOD)

    local_zone = timezone(timedelta(minutes=config.utc_offset_minutes))
    local_now = now.astimezone(local_zone)
    minute = local_now.hour * 60 + local_now.minute
    start = config.allowed_start_minute
    end = config.allowed_end_minute
    overnight = start > end
    window_day = (local_now.weekday() - 1) % 7 if overnight and minute < end else local_now.weekday()
    if window_day not in config.allowed_weekdays:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.WEEKDAY_NOT_ALLOWED,
        )
    inside_window = start <= minute < end if not overnight else minute >= start or minute < end
    if not inside_window:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.OUTSIDE_ALLOWED_WINDOW,
        )
    if state.user_session_active:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.USER_SESSION_ACTIVE,
        )
    if state.awaiting_user_response:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.AWAITING_USER_RESPONSE,
        )

    attempts_today = tuple(
        value for value in state.attempted_at
        if value.astimezone(local_zone).date() == local_now.date()
    )
    if len(attempts_today) >= config.daily_limit:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.DAILY_LIMIT_REACHED,
        )
    if state.attempted_at and now - max(state.attempted_at) < config.minimum_interval:
        return decision(
            OutreachPolicyAction.BLOCK,
            OutreachPolicyReason.MINIMUM_INTERVAL_ACTIVE,
        )
    return decision(OutreachPolicyAction.ALLOW, OutreachPolicyReason.READY)


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field}_timezone_required")
