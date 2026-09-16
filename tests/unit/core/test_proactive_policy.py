"""主动联系策略只使用显式设置和可核对的运行状态。"""

from datetime import UTC, datetime, timedelta

import pytest

from longmemory.core.proactive import (
    OutreachPolicyAction,
    OutreachPolicyConfig,
    OutreachPolicyReason,
    OutreachPolicyState,
    OutreachTrigger,
    ProactiveOutreach,
    decide_outreach,
)


NOW = datetime(2026, 9, 7, 5, 0, tzinfo=UTC)  # 北京时间周一 13:00


def candidate(*, scheduled_for=NOW, expires_at=None):
    created_at = min(NOW - timedelta(minutes=1), scheduled_for)
    return ProactiveOutreach(
        id="outreach-1",
        subject_id="user:self",
        trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
        trigger_reason_code="lunch_check_in",
        content="下午好，今天过得怎么样？",
        created_at=created_at,
        scheduled_for=scheduled_for,
        expires_at=expires_at or scheduled_for + timedelta(minutes=5),
        state_changed_at=created_at,
        idempotency_key="check-in-2026-09-07",
    )


def enabled(**changes):
    values = {
        "enabled": True,
        "allowed_start_minute": 12 * 60,
        "allowed_end_minute": 14 * 60,
    }
    values.update(changes)
    return OutreachPolicyConfig(**values)


def decide(*, outreach=None, state=None, config=None, now=NOW):
    return decide_outreach(
        outreach or candidate(),
        now=now,
        state=state or OutreachPolicyState(),
        config=config or enabled(),
    )


def test_disabled_by_default_and_enabled_candidate_is_ready():
    off = decide(config=OutreachPolicyConfig())
    ready = decide()
    assert (off.action, off.reason) == (
        OutreachPolicyAction.BLOCK, OutreachPolicyReason.DISABLED,
    )
    assert (ready.action, ready.reason, ready.policy_version) == (
        OutreachPolicyAction.ALLOW,
        OutreachPolicyReason.READY,
        "proactive-contact-policy-v3",
    )


def test_future_candidate_waits_but_expired_candidate_is_never_replayed():
    future = NOW + timedelta(minutes=2)
    waiting = decide(outreach=candidate(scheduled_for=future))
    expired = decide(
        outreach=candidate(
            scheduled_for=NOW - timedelta(minutes=6),
            expires_at=NOW,
        )
    )
    assert (waiting.action, waiting.reason, waiting.next_eligible_at) == (
        OutreachPolicyAction.WAIT, OutreachPolicyReason.NOT_DUE, future,
    )
    assert (expired.action, expired.reason, expired.next_eligible_at) == (
        OutreachPolicyAction.BLOCK, OutreachPolicyReason.EXPIRED, None,
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (
            OutreachPolicyState(quiet_until=NOW + timedelta(hours=1)),
            OutreachPolicyReason.QUIET_PERIOD,
        ),
        (
            OutreachPolicyState(user_session_active=True),
            OutreachPolicyReason.USER_SESSION_ACTIVE,
        ),
        (
            OutreachPolicyState(awaiting_user_response=True),
            OutreachPolicyReason.AWAITING_USER_RESPONSE,
        ),
        (
            OutreachPolicyState(attempted_at=(NOW - timedelta(hours=1),)),
            OutreachPolicyReason.DAILY_LIMIT_REACHED,
        ),
    ],
)
def test_explicit_safety_and_frequency_guards_block_without_deferral(state, reason):
    result = decide(state=state)
    assert (result.action, result.reason, result.next_eligible_at) == (
        OutreachPolicyAction.BLOCK, reason, None,
    )


def test_minimum_interval_applies_across_local_date_boundary():
    # 当天次数还没用完，但北京时间凌晨刚联系过，仍受最短间隔限制。
    now = datetime(2026, 9, 7, 16, 30, tzinfo=UTC)  # 周二 00:30
    item = candidate(scheduled_for=now, expires_at=now + timedelta(minutes=5))
    result = decide(
        outreach=item,
        now=now,
        state=OutreachPolicyState(attempted_at=(now - timedelta(hours=1),)),
        config=enabled(
            allowed_start_minute=0,
            allowed_end_minute=2 * 60,
            daily_limit=2,
        ),
    )
    assert result.reason == OutreachPolicyReason.MINIMUM_INTERVAL_ACTIVE


def test_weekday_and_allowed_window_are_interpreted_in_configured_offset():
    weekend_only = decide(config=enabled(allowed_weekdays=(5, 6)))
    outside = decide(config=enabled(allowed_start_minute=18 * 60, allowed_end_minute=22 * 60))
    assert weekend_only.reason == OutreachPolicyReason.WEEKDAY_NOT_ALLOWED
    assert outside.reason == OutreachPolicyReason.OUTSIDE_ALLOWED_WINDOW


def test_overnight_window_uses_the_day_on_which_the_window_started():
    monday_2330 = datetime(2026, 9, 7, 15, 30, tzinfo=UTC)
    tuesday_0100 = datetime(2026, 9, 7, 17, 0, tzinfo=UTC)
    config = enabled(
        allowed_weekdays=(0,),
        allowed_start_minute=22 * 60,
        allowed_end_minute=2 * 60,
        minimum_interval=timedelta(0),
    )
    for now in (monday_2330, tuesday_0100):
        item = candidate(scheduled_for=now, expires_at=now + timedelta(minutes=5))
        assert decide(outreach=item, now=now, config=config).reason == OutreachPolicyReason.READY


def test_overlong_window_and_invalid_or_untrusted_times_are_rejected():
    overlong = decide(
        outreach=candidate(expires_at=NOW + timedelta(minutes=6)),
    )
    assert overlong.reason == OutreachPolicyReason.WINDOW_TOO_LONG
    with pytest.raises(ValueError, match="outreach_policy_config_invalid"):
        enabled(allowed_start_minute=60, allowed_end_minute=60)
    with pytest.raises(ValueError, match="outreach_policy_now_timezone_required"):
        decide(now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="outreach_attempt_in_future"):
        decide(state=OutreachPolicyState(attempted_at=(NOW + timedelta(seconds=1),)))
