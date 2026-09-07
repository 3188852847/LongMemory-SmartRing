"""显式定时触发只在配置分钟内做一次可解释决定。"""

from datetime import UTC, datetime

import pytest

from longmemory.core.proactive import (
    OutreachPolicyConfig,
    ProactivePolicySettings,
    ScheduledTriggerAction,
    ScheduledTriggerReason,
    decide_scheduled_trigger,
)


NOW = datetime(2026, 9, 7, 5, 0, 15, tzinfo=UTC)  # 北京时间周一 13:00。


def settings(**changes):
    values = {"automatic_enabled": True, "scheduled_minute": 13 * 60}
    values.update(changes)
    return ProactivePolicySettings(
        "user:self", OutreachPolicyConfig(enabled=True), **values,
    )


def decide(**changes):
    values = {
        "settings": settings(),
        "now": NOW,
        "user_chatted_today": False,
        "already_evaluated_today": False,
    }
    values.update(changes)
    return decide_scheduled_trigger(**values)


def test_exact_minute_creates_stable_daily_candidate_identity():
    result = decide()
    assert result.action == ScheduledTriggerAction.CREATE
    assert result.reason == ScheduledTriggerReason.READY
    assert result.idempotency_key == "explicit-schedule:2026-09-07"
    assert result.scheduled_for == datetime(2026, 9, 7, 5, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"settings": settings(automatic_enabled=False)}, "automatic_disabled"),
        ({"user_chatted_today": True}, "user_already_chatted_today"),
        ({"already_evaluated_today": True}, "already_evaluated_today"),
    ],
)
def test_safety_conditions_skip_without_creating_candidate(changes, reason):
    result = decide(**changes)
    assert (result.action.value, result.reason.value) == ("skip", reason)


def test_before_time_waits_but_missed_minute_is_never_caught_up():
    before = decide(now=NOW.replace(hour=4, minute=59))
    missed = decide(now=NOW.replace(hour=5, minute=1))
    assert (before.action, before.reason) == (
        ScheduledTriggerAction.WAIT, ScheduledTriggerReason.BEFORE_SCHEDULE,
    )
    assert (missed.action, missed.reason) == (
        ScheduledTriggerAction.SKIP, ScheduledTriggerReason.MISSED_SCHEDULE,
    )


def test_invalid_time_and_greeting_are_rejected_at_settings_boundary():
    with pytest.raises(ValueError, match="scheduled_minute"):
        settings(scheduled_minute=1440)
    with pytest.raises(ValueError, match="greeting"):
        settings(greeting_text=" 带空格")
    with pytest.raises(ValueError, match="topic_boundary"):
        settings(automatic_enabled=False, topic_enabled=True)
