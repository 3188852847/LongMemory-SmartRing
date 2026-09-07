from datetime import UTC, datetime, timedelta

import pytest

from longmemory.core.proactive import (
    OutreachState,
    OutreachTrigger,
    ProactiveOutreach,
    transition_outreach,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def candidate() -> ProactiveOutreach:
    return ProactiveOutreach(
        id="outreach-1",
        subject_id="user:self",
        trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
        trigger_reason_code="user_schedule",
        content="下午好，记得休息一下。",
        created_at=NOW,
        scheduled_for=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1, minutes=30),
        state_changed_at=NOW,
        idempotency_key="schedule-2026-09-06-13",
        policy_version="proactive-policy-v1",
    )


def test_transition_is_forward_only_and_revisioned():
    queued = transition_outreach(
        candidate(), new_state=OutreachState.QUEUED,
        occurred_at=NOW + timedelta(hours=1),
    )
    assert queued.state == OutreachState.QUEUED and queued.revision == 2
    sent = transition_outreach(
        queued, new_state=OutreachState.TRANSPORT_SENT,
        occurred_at=NOW + timedelta(hours=1, seconds=1),
    )
    assert sent.state == OutreachState.TRANSPORT_SENT and sent.revision == 3


def test_user_observation_can_confirm_playback_from_server_queue():
    queued = transition_outreach(
        candidate(), new_state=OutreachState.QUEUED,
        occurred_at=NOW + timedelta(hours=1),
    )
    played = transition_outreach(
        queued, new_state=OutreachState.PLAYED,
        occurred_at=NOW + timedelta(hours=1, seconds=1),
    )
    assert played.state == OutreachState.PLAYED and played.revision == 3


@pytest.mark.parametrize("target", [
    OutreachState.PLAYED,
    OutreachState.DEVICE_ACKNOWLEDGED,
    OutreachState.TRANSPORT_SENT,
    OutreachState.CANDIDATE,
])
def test_candidate_cannot_skip_unobserved_delivery_states(target):
    with pytest.raises(ValueError, match="outreach_transition_invalid"):
        transition_outreach(candidate(), new_state=target, occurred_at=NOW + timedelta(hours=1))


def test_terminal_state_cannot_be_reopened():
    blocked = transition_outreach(
        candidate(), new_state=OutreachState.BLOCKED,
        occurred_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="outreach_transition_invalid"):
        transition_outreach(
            blocked, new_state=OutreachState.QUEUED,
            occurred_at=NOW + timedelta(minutes=2),
        )


def test_failure_requires_stable_reason_and_other_states_forbid_it():
    queued = transition_outreach(
        candidate(), new_state=OutreachState.QUEUED,
        occurred_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="outreach_failure_reason_required"):
        transition_outreach(
            queued, new_state=OutreachState.FAILED,
            occurred_at=NOW + timedelta(hours=1, seconds=1),
        )
    failed = transition_outreach(
        queued, new_state=OutreachState.FAILED,
        occurred_at=NOW + timedelta(hours=1, seconds=1),
        failure_reason="bridge_unavailable",
    )
    assert failed.failure_reason == "bridge_unavailable"


def test_times_require_timezone_and_valid_window():
    with pytest.raises(ValueError, match="outreach_created_at_timezone_required"):
        ProactiveOutreach(
            id="x", subject_id="user:self", trigger=OutreachTrigger.MANUAL_TEST,
            trigger_reason_code="manual", content="测试",
            created_at=NOW.replace(tzinfo=None), scheduled_for=NOW,
            expires_at=NOW + timedelta(minutes=1), idempotency_key="key",
        )
