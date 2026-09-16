from datetime import UTC, datetime, timedelta
from enum import Enum
from types import SimpleNamespace

from longmemory.entrypoints.api.proactive_presenters import (
    absence_selection_json,
    absence_strategy_version_json,
    absence_switch_event_json,
    follow_up_json,
    outreach_result_json,
    proactive_policy_json,
    routine_candidate_json,
    strategy_candidate_json,
    topic_seed_json,
)


NOW = datetime(2026, 9, 11, 4, 0, tzinfo=UTC)


class Value(Enum):
    ACTIVE = "active"
    ALLOW = "allow"


class Sources:
    def __init__(self, field):
        self.field = field

    def list_sources(self, _candidate_id):
        return [{self.field: "2026-09-11T03:30:00+00:00", "source_id": "s1"}]


def test_policy_and_topic_seed_projection_keep_public_contract():
    config = SimpleNamespace(
        enabled=True, utc_offset_minutes=480, allowed_weekdays=(0, 1),
        allowed_start_minute=480, allowed_end_minute=1320, daily_limit=2,
        minimum_interval=timedelta(hours=2), maximum_lifetime=timedelta(minutes=30),
        policy_version="policy-v1",
    )
    settings = SimpleNamespace(
        subject_id="user:self", config=config, quiet_until=None, revision=3,
        updated_at=NOW, automatic_enabled=True, scheduled_minute=780,
        greeting_text="下午好", topic_enabled=True, automatic_interval_seconds=600,
    )
    assert proactive_policy_json(settings)["minimum_interval_seconds"] == 7200
    assert proactive_policy_json(settings)["automatic_interval_seconds"] == 600

    row = {
        "id": "seed", "subject_id": "user:self", "scenario_id": "l2",
        "prompt_text": "最近怎么样", "status": "active", "created_at": "created",
        "updated_at": "updated", "revision": 1, "scenario_title": "近况",
        "scenario_summary": "准备汇报", "scenario_status": "active",
        "scenario_valid_from": None, "scenario_valid_to": None,
    }
    assert topic_seed_json(row, now=NOW)["usable"] is True


def test_follow_up_projection_explains_ready_and_changed_sources():
    row = {
        "id": "follow", "subject_id": "user:self", "source_memory_id": "l1",
        "prompt_text": "汇报怎么样", "follow_up_at": "2026-09-11T05:00:00+00:00",
        "status": "candidate", "created_at": "created", "updated_at": "updated",
        "revision": 1, "creation_kind": "explicit", "source_message_id": "m1",
        "source_content": "用户五点汇报", "source_retired_at": None,
        "source_valid_from": None, "source_valid_to": None,
        "source_content_sha256": __import__("hashlib").sha256(
            "用户五点汇报".encode("utf-8")
        ).hexdigest(),
        "source_superseded_by_id": None, "outreach_id": None,
        "outreach_state": None, "outreach_revision": None,
        "outreach_expires_at": None,
    }
    assert follow_up_json(row, now=NOW)["ready_for_activation"] is True
    row["source_content_sha256"] = "0" * 64
    changed = follow_up_json(row, now=NOW)
    assert changed["ready_for_activation"] is False
    assert changed["blocked_reason"] == "source_changed"


def test_candidate_and_absence_projections_add_local_time_and_active_state():
    strategy = SimpleNamespace(
        id="strategy", subject_id="user:self", status=Value.ACTIVE,
        suggested_minute=750, utc_offset_minutes=480, evidence_count=4,
        distinct_local_dates=3, rationale_code="routine", generator_version="v1",
        created_at=NOW, updated_at=NOW, revision=2,
    )
    assert strategy_candidate_json(strategy, Sources("queued_at"))["sources"][0][
        "local_minute"
    ] == 690

    routine = SimpleNamespace(
        **strategy.__dict__, expected_minute=750, observation_window_minutes=30,
    )
    del routine.suggested_minute
    assert routine_candidate_json(routine, Sources("occurred_at"))["active"] is False

    version = SimpleNamespace(
        id="v1", subject_id="user:self", source_candidate_id="routine",
        source_candidate_revision=2, expected_minute=750, grace_minutes=30,
        utc_offset_minutes=480, allowed_weekdays=(0, 1), trigger_policy_version="p1",
        replay_protocol="r1", replay_dataset_name="synthetic",
        replay_dataset_version="1", replay_dataset_sha256="a" * 64,
        parameter_fingerprint="b" * 64, replay_case_count=2,
        replay_matched_count=2, replay_unsafe_allow_count=0,
        replay_gate_passed=True, replayed_at=NOW, created_at=NOW,
    )
    assert absence_strategy_version_json(version, active=True)["active"] is True


def test_outreach_selection_and_switch_event_projection_are_stable():
    outreach = SimpleNamespace(id="o1", state=Value.ACTIVE, revision=4)
    device = SimpleNamespace(ready=True, user_session_active=False, reason_code=None)
    result = outreach_result_json(outreach, replayed=False, device=device)
    assert result["device"] == {
        "ready": True, "user_session_active": False, "reason": None,
    }
    assert absence_selection_json(None)["revision"] == 0

    selection = SimpleNamespace(version_id="v1", revision=2, updated_at=NOW)
    assert absence_selection_json(selection)["current_version_id"] == "v1"
    event = SimpleNamespace(
        id="e1", previous_version_id=None, selected_version_id="v1",
        action=Value.ALLOW, pointer_revision=2, created_at=NOW,
    )
    assert absence_switch_event_json(event)["action"] == "allow"
