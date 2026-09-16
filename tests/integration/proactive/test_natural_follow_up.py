import asyncio
from datetime import UTC, datetime, timedelta
import json
import sqlite3

from longmemory.adapters.storage.sqlite_natural_memory_commands import (
    SQLiteNaturalMemoryCommandHandler,
)
from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.bootstrap import build_memory_runtime
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.methods.daily_llm.method import DailyLLMMemory


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


def test_explicit_voice_reschedule_replaces_recent_follow_up_atomically(tmp_path):
    path = tmp_path / "natural-follow-up-reschedule.db"
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
    original = runtime.prepare_user(
        "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()
    assert original.follow_up_suggestion.status == "candidate_armed"

    changed_at = NOW + timedelta(minutes=1)
    runtime = build_memory_runtime(path, clock=lambda: changed_at)
    changed = runtime.prepare_user("请把时间改成16点30分。")
    runtime.close()

    assert changed.memory_command is not None
    assert changed.memory_command.kind == "reschedule_follow_up"
    assert changed.memory_command.status == "applied"
    assert "16:30" in changed.memory_command.notice
    assert changed.observation.writes == ()
    connection = open_database(path)
    candidates = connection.execute(
        "SELECT status,revision,follow_up_at,source_memory_id "
        "FROM companion_follow_up_candidates ORDER BY created_at,id"
    ).fetchall()
    assert [tuple(row[:3]) for row in candidates] == [
        ("cancelled", 2, "2026-09-11T15:00:00+08:00"),
        ("candidate", 1, "2026-09-11T16:30:00+08:00"),
    ]
    assert candidates[0][3] == candidates[1][3]
    outreach = connection.execute(
        "SELECT state,revision,scheduled_for FROM proactive_outreach "
        "ORDER BY created_at,id"
    ).fetchall()
    assert [tuple(row) for row in outreach] == [
        ("cancelled", 2, "2026-09-11T15:00:00+08:00"),
        ("candidate", 1, "2026-09-11T16:30:00+08:00"),
    ]
    assert connection.execute(
        "SELECT reason_code FROM proactive_outreach_events "
        "WHERE outreach_id=? AND sequence=2",
        (original.follow_up_suggestion.outreach_id,),
    ).fetchone()[0] == "user_rescheduled_recent_follow_up"
    assert connection.execute(
        "SELECT count(*) FROM atomic_memories"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT count(*) FROM conversation_messages "
        "WHERE content='请把时间改成16点30分。'"
    ).fetchone()[0] == 1
    connection.close()


def test_rescheduled_voice_follow_up_delivers_only_at_new_time_after_restart(
    tmp_path,
):
    """追加式改时必须改变真实后台投递，而不只改变候选页面。"""

    path = tmp_path / "natural-follow-up-reschedule-delivery.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self", OutreachPolicyConfig(
                enabled=True, daily_limit=2, minimum_interval=timedelta(0),
            ),
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
    changed_at = NOW + timedelta(minutes=1)
    runtime = build_memory_runtime(path, clock=lambda: changed_at)
    changed = runtime.prepare_user("请把时间改成16点30分。")
    runtime.close()
    assert changed.memory_command.status == "applied"

    class ReadyBridge:
        def __init__(self):
            self.announcements = []

        async def status(self):
            return {
                "connection_count": 1, "ready": True,
                "announcement_supported": True, "announcement_ready": True,
                "user_session_active": False,
            }

        async def announce(self, text, expires_at):
            self.announcements.append((text, expires_at))
            return {"state": "queued"}

    bridge = ReadyBridge()
    old_time = datetime.fromisoformat("2026-09-11T15:00:00+08:00")
    new_time = datetime.fromisoformat("2026-09-11T16:30:00+08:00")

    # 每次创建新的 Backend，模拟服务停止后依靠 SQLite 账本恢复调度。
    old_result = asyncio.run(
        MemoryBackend(path, clock=lambda: old_time).proactive_follow_up_tick(
            bridge
        )
    )
    delivered = asyncio.run(
        MemoryBackend(path, clock=lambda: new_time).proactive_follow_up_tick(
            bridge
        )
    )
    duplicate = asyncio.run(
        MemoryBackend(path, clock=lambda: new_time).proactive_follow_up_tick(
            bridge
        )
    )

    assert old_result == {
        "action": "skip", "reason": "no_due_follow_up",
        "suppress_lower_priority": False,
    }
    assert delivered["state"] == "queued"
    assert len(bridge.announcements) == 1
    assert duplicate == {
        "action": "skip",
        "reason": "follow_up_already_handled_this_minute",
        "suppress_lower_priority": True,
    }


def test_follow_up_reschedule_rejects_past_time_without_changing_original(tmp_path):
    path = tmp_path / "natural-follow-up-reschedule-past.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    runtime.prepare_user(
        "我今天下午三点要提交毕业设计汇报，到时候问我汇报进展"
    )
    runtime.close()

    runtime = build_memory_runtime(
        path, clock=lambda: NOW + timedelta(minutes=1),
    )
    result = runtime.prepare_user("请把时间改成上午八点。")
    runtime.close()

    assert result.memory_command is not None
    assert result.memory_command.kind == "reschedule_follow_up"
    assert result.memory_command.status == "time_not_future"
    connection = open_database(path)
    assert tuple(connection.execute(
        "SELECT status,revision,follow_up_at "
        "FROM companion_follow_up_candidates"
    ).fetchone()) == ("candidate", 1, "2026-09-10T15:00:00+08:00")
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


def test_explicit_round_screen_follow_up_finishes_llm_write_before_reply(tmp_path):
    """明确跟进不能先让回答模型否认能力、再在后台静默创建候选。"""

    path = tmp_path / "synchronous-round-screen-follow-up.db"
    prepare(path)
    connection = open_database(path)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(
                enabled=True, daily_limit=2, minimum_interval=timedelta(0),
            ),
            revision=1,
            updated_at=NOW,
        ),
        expected_revision=0,
    )
    connection.close()

    class Producer:
        def propose(self, **_kwargs):
            return json.dumps({
                "schema_version": 1,
                "operation": "ADD",
                "facts": [{
                    "content": "用户明天下午三点要提交毕业设计汇报。",
                    "quote": "我明天下午三点要提交毕业设计汇报",
                }],
            }, ensure_ascii=False)

    method = DailyLLMMemory(
        path, producer=Producer(), allow_cross_thread=True,
    )
    runtime = MemoryRuntime(
        path,
        method=method,
        memory_command_handler=SQLiteNaturalMemoryCommandHandler(path),
        clock=lambda: NOW,
    )
    try:
        prepared = runtime.prepare_user(
            "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展",
            defer_slow_observation=True,
        )
        assert prepared.observation.processing_status == "completed"
        assert prepared.observation.warning_code is None
        assert prepared.follow_up_suggestion is not None
        assert prepared.follow_up_suggestion.status == "candidate_armed"
        assert (
            runtime.status()["deferred_observation"]["running_or_queued"] == 0
        )
    finally:
        runtime.close()


def test_explicit_follow_up_reports_not_created_when_memory_write_is_disabled(
    tmp_path,
):
    path = tmp_path / "write-disabled-round-screen-follow-up.db"
    prepare(path)
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    try:
        runtime.configure(write_enabled=False, use_enabled=True)
        prepared = runtime.prepare_user(
            "我明天下午三点要提交毕业设计汇报，到时候问我汇报进展",
            defer_slow_observation=True,
        )
        assert prepared.observation.writes == ()
        assert prepared.follow_up_suggestion is not None
        assert prepared.follow_up_suggestion.status == "not_created"
        assert prepared.follow_up_suggestion.warning_code == (
            "follow_up_memory_write_disabled"
        )
    finally:
        runtime.close()
