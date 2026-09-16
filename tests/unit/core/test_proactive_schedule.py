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
    config = values.pop("config", OutreachPolicyConfig(enabled=True))
    return ProactivePolicySettings(
        "user:self", config, **values,
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


def test_interval_mode_creates_each_matching_slot_and_does_not_skip_after_chat():
    interval = settings(automatic_interval_seconds=10 * 60, scheduled_minute=12 * 60)
    first = decide(settings=interval, now=NOW.replace(hour=4, minute=0),
                   user_chatted_today=True)
    between = decide(settings=interval, now=NOW.replace(hour=4, minute=5))
    second = decide(settings=interval, now=NOW.replace(hour=4, minute=10))
    assert first.action == ScheduledTriggerAction.CREATE
    assert first.idempotency_key == "interval-schedule:2026-09-07T04:00+00:00"
    assert (between.action.value, between.reason.value) == ("wait", "between_intervals")
    assert second.action == ScheduledTriggerAction.CREATE
    assert second.idempotency_key == "interval-schedule:2026-09-07T04:10+00:00"


def test_interval_does_not_backdate_current_minute_after_setting_changes():
    just_changed = settings(
        automatic_interval_seconds=60,
        revision=1,
        updated_at=NOW,
    )
    result = decide(settings=just_changed, now=NOW)
    assert (result.action.value, result.reason.value) == ("wait", "between_intervals")


def test_interval_keeps_its_continuous_phase_across_local_midnight():
    interval = settings(
        automatic_interval_seconds=7 * 60,
        scheduled_minute=23 * 60 + 56,
        config=OutreachPolicyConfig(
            enabled=True, allowed_start_minute=0, allowed_end_minute=1439,
        ),
        revision=1,
        updated_at=datetime(2026, 9, 7, 15, 55, 30, tzinfo=UTC),
    )
    result = decide(
        settings=interval,
        now=datetime(2026, 9, 7, 16, 3, 20, tzinfo=UTC),
    )
    assert result.action == ScheduledTriggerAction.CREATE
    assert result.idempotency_key == "interval-schedule:2026-09-07T16:03+00:00"


@pytest.mark.parametrize("seconds", [59, 61, 86460])
def test_interval_requires_whole_minutes_between_one_minute_and_one_day(seconds):
    with pytest.raises(ValueError, match="automatic_interval"):
        settings(automatic_interval_seconds=seconds)


def test_invalid_time_and_greeting_are_rejected_at_settings_boundary():
    with pytest.raises(ValueError, match="scheduled_minute"):
        settings(scheduled_minute=1440)
    with pytest.raises(ValueError, match="greeting"):
        settings(greeting_text=" 带空格")
    with pytest.raises(ValueError, match="topic_boundary"):
        settings(automatic_enabled=False, topic_enabled=True)
