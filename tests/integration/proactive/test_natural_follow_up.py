from datetime import UTC, datetime, timedelta
import sqlite3

from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.bootstrap import build_memory_runtime
from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def prepare(path):
    connection = open_database(path)
    initialize_schema(connection)
    connection.close()


def test_explicit_conversation_request_creates_unarmed_traceable_candidate(tmp_path):
    path = tmp_path / "natural-follow-up.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)

    prepared = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()

    suggestion = prepared.follow_up_suggestion
    assert suggestion is not None
    assert suggestion.status == "candidate_created_requires_proactive_enabled"
    assert suggestion.prompt_text == "汇报进展？"
    connection = open_database(path)
    row = connection.execute(
        "SELECT * FROM companion_follow_up_candidates"
    ).fetchone()
    assert row["creation_kind"] == "explicit_conversation_request"
    assert row["source_message_id"] == prepared.event.event_id
    assert row["source_memory_id"] == suggestion.source_memory_id
    assert connection.execute(
        "SELECT count(*) FROM proactive_outreach"
    ).fetchone()[0] == 0
    connection.close()


def test_explicit_request_atomically_arms_when_proactive_is_enabled(tmp_path):
    path = tmp_path / "natural-follow-up-enabled.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(
                enabled=True, daily_limit=2,
                minimum_interval=timedelta(0),
            ),
            revision=1, updated_at=NOW,
        ),
        expected_revision=0,
    )
    connection.close()
    runtime = build_memory_runtime(path, clock=lambda: NOW)

    prepared = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()

    suggestion = prepared.follow_up_suggestion
    assert suggestion is not None
    assert suggestion.status == "candidate_armed"
    assert suggestion.outreach_id is not None
    connection = open_database(path)
    outreach = connection.execute(
        "SELECT * FROM proactive_outreach"
    ).fetchone()
    assert outreach["id"] == suggestion.outreach_id
    assert outreach["state"] == "candidate"
    assert outreach["trigger_kind"] == "explicit_schedule"
    assert outreach["trigger_reason_code"] == "conversation_authorized_l1_follow_up"
    assert outreach["follow_up_candidate_id"] == suggestion.candidate_id
    assert outreach["follow_up_candidate_revision"] == 1
    assert outreach["scheduled_for"] == suggestion.follow_up_at
    connection.close()


def test_outreach_failure_rolls_back_candidate_but_preserves_committed_memory(
    tmp_path, monkeypatch,
):
    path = tmp_path / "natural-follow-up-atomic-failure.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self", OutreachPolicyConfig(enabled=True),
            revision=1, updated_at=NOW,
        ),
        expected_revision=0,
    )
    connection.close()

    def fail_outreach(_self, _outreach, _event):
        raise sqlite3.IntegrityError("synthetic_outreach_failure")

    monkeypatch.setattr(SQLiteProactiveOutreachStore, "create", fail_outreach)
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    prepared = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()

    assert prepared.follow_up_suggestion is not None
    assert prepared.follow_up_suggestion.status == "not_created"
    assert (
        prepared.follow_up_suggestion.warning_code
        == "follow_up_atomic_activation_failed"
    )
    connection = open_database(path)
    assert connection.execute(
        "SELECT count(*) FROM atomic_memories"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM proactive_outreach"
    ).fetchone()[0] == 0
    connection.close()


def test_explicit_voice_cancellation_stops_the_only_recent_follow_up(tmp_path):
    path = tmp_path / "natural-follow-up-cancel.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self", OutreachPolicyConfig(enabled=True),
            revision=1, updated_at=NOW,
        ),
        expected_revision=0,
    )
    connection.close()
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    scheduled = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()
    assert scheduled.follow_up_suggestion.status == "candidate_armed"

    cancelled_at = NOW + timedelta(minutes=1)
    runtime = build_memory_runtime(path, clock=lambda: cancelled_at)
    cancelled = runtime.prepare_user("取消刚才的跟进")
    runtime.close()

    assert cancelled.memory_command is not None
    assert cancelled.memory_command.kind == "cancel_follow_up"
    assert cancelled.memory_command.status == "applied"
    assert cancelled.observation.writes == ()
    connection = open_database(path)
    assert tuple(connection.execute(
        "SELECT status,revision FROM companion_follow_up_candidates"
    ).fetchone()) == ("cancelled", 2)
    assert tuple(connection.execute(
        "SELECT state,revision FROM proactive_outreach"
    ).fetchone()) == ("cancelled", 2)
    assert connection.execute(
        "SELECT reason_code FROM proactive_outreach_events WHERE sequence=2"
    ).fetchone()[0] == "user_cancelled_recent_follow_up"
    assert connection.execute(
        "SELECT count(*) FROM conversation_messages WHERE content='取消刚才的跟进'"
    ).fetchone()[0] == 1
    connection.close()


def test_voice_cancellation_refuses_to_guess_between_two_recent_follow_ups(tmp_path):
    path = tmp_path / "natural-follow-up-ambiguous-cancel.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self", OutreachPolicyConfig(enabled=True),
            revision=1, updated_at=NOW,
        ),
        expected_revision=0,
    )
    connection.close()
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()
    runtime = build_memory_runtime(
        path, clock=lambda: NOW + timedelta(seconds=30),
    )
    runtime.prepare_user(
        "我后天下午四点要参加项目会议，到时候问我会议结果"
    )
    runtime.close()

    runtime = build_memory_runtime(path, clock=lambda: NOW + timedelta(minutes=1))
    result = runtime.prepare_user("不用到时候问我了")
    runtime.close()

    assert result.memory_command is not None
    assert result.memory_command.kind == "cancel_follow_up"
    assert result.memory_command.status == "target_ambiguous"
    connection = open_database(path)
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates WHERE status='candidate'"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT count(*) FROM proactive_outreach WHERE state='candidate'"
    ).fetchone()[0] == 2
    connection.close()


def test_vague_plan_keeps_memory_but_does_not_create_candidate(tmp_path):
    path = tmp_path / "vague-follow-up.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)

    prepared = runtime.prepare_user("我以后打算认真准备毕业设计")
    runtime.close()

    assert prepared.observation.writes
    assert prepared.follow_up_suggestion is None
    connection = open_database(path)
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    connection.close()
