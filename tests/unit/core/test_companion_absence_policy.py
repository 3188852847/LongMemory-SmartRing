"""日常时段缺席判断不能把“规律”直接等同于“应该联系”。"""

from datetime import UTC, datetime

import pytest

from longmemory.core.companion import (
    AbsenceRoutineDraft,
    AbsenceRoutineState,
    AbsenceTriggerAction,
    AbsenceTriggerReason,
    decide_routine_absence,
)


NOW = datetime(2026, 9, 7, 6, 0, 15, tzinfo=UTC)  # 北京时间周一 14:00。


def draft(**changes):
    values = {"candidate_id": "routine-1", "expected_minute": 13 * 60, "enabled": True}
    values.update(changes)
    return AbsenceRoutineDraft(**values)


def test_exact_check_minute_creates_stable_daily_candidate():
    result = decide_routine_absence(draft(), now=NOW, state=AbsenceRoutineState())
    assert result.action == AbsenceTriggerAction.CREATE
    assert result.reason == AbsenceTriggerReason.READY
    assert result.idempotency_key == "routine-absence:routine-1:2026-09-07"
    assert result.check_at == datetime(2026, 9, 7, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (AbsenceRoutineState(routine_observed_today=True), "routine_observed_today"),
        (AbsenceRoutineState(user_chatted_today=True), "user_already_chatted_today"),
        (AbsenceRoutineState(already_evaluated_today=True), "already_evaluated_today"),
    ],
)
def test_observed_or_evaluated_day_never_creates_candidate(state, reason):
    result = decide_routine_absence(draft(), now=NOW, state=state)
    assert (result.action.value, result.reason.value) == ("skip", reason)


def test_before_check_waits_and_missed_check_never_catches_up():
    before = decide_routine_absence(draft(), now=NOW.replace(hour=5, minute=59), state=AbsenceRoutineState())
    missed = decide_routine_absence(draft(), now=NOW.replace(minute=1), state=AbsenceRoutineState())
    assert (before.action.value, before.reason.value) == ("wait", "before_absence_check")
    assert (missed.action.value, missed.reason.value) == ("skip", "missed_absence_check")


def test_cross_midnight_v1_and_naive_time_are_rejected():
    with pytest.raises(ValueError, match="absence_routine_draft_invalid"):
        draft(expected_minute=23 * 60 + 30, grace_minutes=60)
    with pytest.raises(ValueError, match="timezone_required"):
        decide_routine_absence(
            draft(), now=datetime(2026, 9, 7, 14), state=AbsenceRoutineState(),
        )
