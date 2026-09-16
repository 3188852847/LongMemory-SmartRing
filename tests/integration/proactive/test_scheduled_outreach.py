"""定时问候合成链：真实 SQLite、模拟圆屏桥，不访问个人数据或设备。"""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.adapters.storage.sqlite_proactive_schedule_override_store import (
    SQLiteProactiveScheduleOverrideStore,
)
from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import (
    SQLiteCompanionAbsenceStrategyVersionStore,
)
from longmemory.application.companion_absence_strategy import (
    CompanionAbsenceStrategyVersionService,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.core.companion import CompanionStrategyReplayEvidence
from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachPolicyConfig,
    OutreachState,
    OutreachTrigger,
    ProactivePolicySettings,
)
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 5, 0, 10, tzinfo=UTC)  # 北京时间周一 13:00。


class ReadyBridge:
    def __init__(self):
        self.announcements = []

    async def status(self):
        return {
            "connection_count": 1,
            "ready": True,
            "read_volume_supported": True,
            "set_volume_supported": True,
            "announcement_supported": True,
            "announcement_ready": True,
            "user_session_active": False,
            "allowed_volume": {"minimum": 5, "maximum": 100},
        }

    async def announce(self, text, expires_at):
        self.announcements.append((text, expires_at))
        return {"state": "queued"}


class OfflineBridge(ReadyBridge):
    async def status(self):
        value = await super().status()
        return {**value, "connection_count": 0, "ready": False,
                "announcement_ready": False, "reason": "device_offline"}


def prepare(
    path, *, user_chatted=False, topic_enabled=False, development_budget=False,
    automatic_interval_seconds=86400,
):
    connection = open_database(path)
    initialize_schema(connection)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(
                enabled=True,
                daily_limit=(
                    3 if development_budget else 86400 // automatic_interval_seconds
                ),
                minimum_interval=(
                    timedelta(0) if development_budget else timedelta(
                        seconds=max(0, automatic_interval_seconds - 60),
                    )
                ),
            ),
            revision=1,
            updated_at=NOW - timedelta(minutes=1),
            automatic_enabled=True,
            scheduled_minute=13 * 60,
            greeting_text="固定合成问候。",
            topic_enabled=topic_enabled,
            automatic_interval_seconds=automatic_interval_seconds,
        ),
        expected_revision=0,
    )
    if user_chatted:
        connection.execute(
            "INSERT INTO conversation_messages(id,role,content,created_at) "
            "VALUES ('synthetic-user-message','user','合成文本',?)",
            (NOW.replace(hour=1).isoformat(),),
        )
        connection.commit()
    connection.close()


def add_topic_seed(path):
    connection = open_database(path)
    connection.execute(
        "INSERT INTO scenario_memories "
        "(id,subject_id,title,summary,generated_at,valid_from,valid_to,status,"
        "generator_name,generator_version,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("scenario-topic", "user:self", "毕业设计", "用户正在准备毕业设计汇报。",
         NOW.isoformat(), None, None, "active", "test", "1", 2),
    )
    connection.execute(
        "INSERT INTO proactive_topic_seeds "
        "(id,subject_id,scenario_id,prompt_text,status,created_at,updated_at,revision) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("b" * 32, "user:self", "scenario-topic", "毕业设计准备得怎么样了？",
         "active", NOW.isoformat(), NOW.isoformat(), 1),
    )
    connection.commit()
    connection.close()


def activate_absence(path, *, expected_minute=12 * 60):
    connection = open_database(path)
    connection.execute(
        "INSERT INTO companion_routine_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("routine-candidate", "user:self", "candidate", expected_minute, 480, 30,
         3, 3, "a" * 64, "repeated_user_initiated_activity_near_time",
         "test-generator", NOW.isoformat(), NOW.isoformat(), 1),
    )
    connection.commit()
    service = CompanionAbsenceStrategyVersionService(
        SQLiteCompanionAbsenceStrategyVersionStore(connection),
        clock=lambda: NOW,
        id_factory=iter(("absence-version", "absence-activation")).__next__,
    )
    service.create_from_candidate(
        "routine-candidate", subject_id="user:self",
        expected_candidate_revision=1, allowed_weekdays=(0,),
        replay=CompanionStrategyReplayEvidence(
            protocol="companion-absence-offline-replay-v1",
            dataset_name="companion_absence_replay", dataset_version="1.0.0",
            dataset_sha256="b" * 64, case_count=16, matched_count=16,
            unsafe_allow_count=0, gate_passed=True, replayed_at=NOW,
        ),
    )
    service.select_version(
        "absence-version", subject_id="user:self", expected_revision=0,
    )
    connection.close()


def test_exact_minute_dispatches_at_most_once_across_repeated_ticks(tmp_path):
    path = tmp_path / "scheduled.db"
    prepare(path)
    bridge = ReadyBridge()
    backend = MemoryBackend(path, clock=lambda: NOW)

    first = asyncio.run(backend.proactive_scheduled_tick(bridge))
    second = asyncio.run(backend.proactive_scheduled_tick(bridge))

    assert first["state"] == "queued"
    assert second == {"action": "skip", "reason": "already_evaluated_today"}
    assert [item[0] for item in bridge.announcements] == ["固定合成问候。"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_kind,state FROM proactive_outreach"
        ).fetchone() == ("explicit_schedule", "queued")


def test_minute_interval_can_dispatch_next_slot_after_user_replies(tmp_path):
    path = tmp_path / "minute-interval.db"
    prepare(path, automatic_interval_seconds=60)
    bridge = ReadyBridge()
    first_now = NOW + timedelta(seconds=40)

    first = asyncio.run(
        MemoryBackend(path, clock=lambda: first_now).proactive_scheduled_tick(bridge)
    )
    connection = open_database(path)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        ("interval-reply", "user", "收到。", (NOW + timedelta(seconds=50)).isoformat()),
    )
    connection.commit()
    connection.close()
    second_now = NOW + timedelta(seconds=55)
    second = asyncio.run(
        MemoryBackend(path, clock=lambda: second_now).proactive_scheduled_tick(bridge)
    )

    assert first["state"] == "queued"
    assert second["state"] == "queued"
    assert [item[0] for item in bridge.announcements] == ["固定合成问候。"] * 2
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(DISTINCT idempotency_key) FROM proactive_outreach"
        ).fetchone()[0] == 2


def test_active_absence_version_dispatches_once_through_existing_ledger(tmp_path):
    path = tmp_path / "absence-scheduled.db"
    prepare(path)
    activate_absence(path)
    bridge = ReadyBridge()
    backend = MemoryBackend(path, clock=lambda: NOW)

    first = asyncio.run(backend.proactive_absence_tick(bridge))
    second = asyncio.run(backend.proactive_absence_tick(bridge))

    assert first["state"] == "queued"
    assert second == {"action": "skip", "reason": "already_evaluated_today"}
    assert [item[0] for item in bridge.announcements] == ["固定合成问候。"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_kind,trigger_reason_code,state,policy_version,"
            "strategy_version_id,strategy_selection_revision,"
            "strategy_evaluated_local_date "
            "FROM proactive_outreach"
        ).fetchone() == (
            "habit_candidate", "routine_absence_fixed_greeting", "queued",
            "proactive-contact-policy-v3+routine-absence-trigger-v1+selection-r1",
            "absence-version", 1, "2026-09-07",
        )
    history = backend.proactive_history(limit=1)["items"][0]
    assert history["strategy_source"] == {
        "version_id": "absence-version",
        "selection_revision": 1,
        "evaluated_local_date": "2026-09-07",
        "source_candidate_id": "routine-candidate",
        "source_candidate_revision": 1,
        "expected_minute": 720,
        "grace_minutes": 60,
        "utc_offset_minutes": 480,
        "trigger_policy_version": "routine-absence-trigger-v1",
    }


def test_explicit_schedule_wins_when_both_sources_share_the_same_minute(tmp_path):
    path = tmp_path / "two-sources-one-minute.db"
    prepare(path)
    activate_absence(path)
    bridge = ReadyBridge()

    result = asyncio.run(
        MemoryBackend(path, clock=lambda: NOW).proactive_background_tick(bridge)
    )

    assert result["source"] == "explicit_schedule"
    assert result["result"]["state"] == "queued"
    assert [item[0] for item in bridge.announcements] == ["固定合成问候。"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 1
        assert connection.execute(
            "SELECT trigger_kind,strategy_version_id,strategy_selection_revision,"
            "strategy_evaluated_local_date FROM proactive_outreach"
        ).fetchone() == ("explicit_schedule", None, None, None)


def test_absence_without_current_version_does_not_probe_or_create(tmp_path):
    path = tmp_path / "absence-inactive.db"
    prepare(path)
    bridge = ReadyBridge()

    result = asyncio.run(MemoryBackend(path, clock=lambda: NOW).proactive_absence_tick(bridge))

    assert result == {"action": "skip", "reason": "absence_strategy_inactive"}
    assert bridge.announcements == []


def test_routine_observed_today_prevents_absence_outreach(tmp_path):
    path = tmp_path / "absence-observed.db"
    prepare(path)
    activate_absence(path)
    connection = open_database(path)
    connection.execute(
        "INSERT INTO conversation_messages VALUES (?,?,?,?)",
        ("observed-message", "user", "合成消息", (NOW - timedelta(hours=4)).isoformat()),
    )
    connection.execute(
        "INSERT INTO companion_user_initiated_interactions VALUES (?,?,?,?,?,?,?,?)",
        ("observed-event", "user:self", "observed-message",
         (NOW - timedelta(hours=4)).isoformat(), None, None,
         "silence_gap_without_recent_outreach", "user-initiated-interaction-v1"),
    )
    connection.commit()
    connection.close()
    bridge = ReadyBridge()

    result = asyncio.run(MemoryBackend(path, clock=lambda: NOW).proactive_absence_tick(bridge))

    assert result == {"action": "skip", "reason": "routine_observed_today"}
    assert bridge.announcements == []


def test_offline_device_records_blocked_absence_without_delivery(tmp_path):
    path = tmp_path / "absence-offline.db"
    prepare(path)
    activate_absence(path)
    bridge = OfflineBridge()

    result = asyncio.run(MemoryBackend(path, clock=lambda: NOW).proactive_absence_tick(bridge))

    assert result["state"] == "blocked"
    assert bridge.announcements == []
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_kind,state FROM proactive_outreach"
        ).fetchone() == ("habit_candidate", "blocked")


def test_real_user_chat_that_day_skips_without_creating_outreach(tmp_path):
    path = tmp_path / "already-chatted.db"
    prepare(path, user_chatted=True)
    bridge = ReadyBridge()

    result = asyncio.run(
        MemoryBackend(path, clock=lambda: NOW).proactive_scheduled_tick(bridge)
    )

    assert result == {"action": "skip", "reason": "user_already_chatted_today"}
    assert bridge.announcements == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0


def test_enabled_memory_topic_is_dispatched_with_traceable_seed_revision(tmp_path):
    path = tmp_path / "scheduled-topic.db"
    prepare(path, topic_enabled=True)
    add_topic_seed(path)
    bridge = ReadyBridge()

    result = asyncio.run(MemoryBackend(path, clock=lambda: NOW).proactive_scheduled_tick(bridge))

    assert result["state"] == "queued"
    assert [item[0] for item in bridge.announcements] == ["毕业设计准备得怎么样了？"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_reason_code,topic_seed_id,topic_seed_revision "
            "FROM proactive_outreach"
        ).fetchone() == ("approved_memory_topic", "b" * 32, 1)


def test_one_shot_development_override_bypasses_chat_and_awaiting_once(tmp_path):
    path = tmp_path / "development-schedule.db"
    prepare(path, user_chatted=True, topic_enabled=True, development_budget=True)
    add_topic_seed(path)
    connection = open_database(path)
    prior_time = NOW - timedelta(minutes=30)
    ledger = ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection), clock=lambda: prior_time,
        id_factory=iter(("prior-outreach", "prior-created", "prior-queued")).__next__,
    )
    prior = ledger.create_candidate(
        subject_id="user:self", trigger=OutreachTrigger.MANUAL_TEST,
        trigger_reason_code="synthetic_prior", content="上一条合成问候。",
        scheduled_for=prior_time, expires_at=prior_time + timedelta(minutes=5),
        idempotency_key="synthetic-prior",
    )
    ledger.record_transition(
        prior.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="ready", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    SQLiteProactiveScheduleOverrideStore(connection).arm(
        override_id="e" * 32, subject_id="user:self",
        local_date="2026-09-07", scheduled_minute=780,
        policy_revision=1,
        now=NOW - timedelta(minutes=1),
    )
    connection.close()
    bridge = ReadyBridge()

    result = asyncio.run(MemoryBackend(path, clock=lambda: NOW).proactive_scheduled_tick(bridge))

    assert result["state"] == "queued"
    assert [item[0] for item in bridge.announcements] == ["毕业设计准备得怎么样了？"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT status,consumption_reason FROM proactive_schedule_overrides"
        ).fetchone() == ("consumed", "scheduled_attempt_started")
        assert connection.execute(
            "SELECT trigger_reason_code,topic_seed_id FROM proactive_outreach "
            "WHERE id<>?", (prior.id,),
        ).fetchone() == ("development_approved_memory_topic", "b" * 32)


def test_missed_development_override_is_consumed_without_delivery(tmp_path):
    path = tmp_path / "missed-development-schedule.db"
    prepare(path, user_chatted=True)
    connection = open_database(path)
    SQLiteProactiveScheduleOverrideStore(connection).arm(
        override_id="f" * 32, subject_id="user:self",
        local_date="2026-09-07", scheduled_minute=780,
        policy_revision=1,
        now=NOW - timedelta(minutes=1),
    )
    connection.close()
    bridge = ReadyBridge()

    result = asyncio.run(
        MemoryBackend(path, clock=lambda: NOW + timedelta(minutes=1))
        .proactive_scheduled_tick(bridge)
    )

    assert result == {"action": "skip", "reason": "scheduled_minute_missed"}
    assert bridge.announcements == []
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT status,consumption_reason FROM proactive_schedule_overrides"
        ).fetchone() == ("consumed", "scheduled_minute_missed")
        assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0


def test_policy_change_invalidates_development_override_without_delivery(tmp_path):
    path = tmp_path / "changed-development-schedule.db"
    prepare(path, user_chatted=True)
    connection = open_database(path)
    SQLiteProactiveScheduleOverrideStore(connection).arm(
        override_id="c" * 32, subject_id="user:self",
        local_date="2026-09-07", scheduled_minute=780,
        policy_revision=1,
        now=NOW - timedelta(minutes=1),
    )
    connection.execute(
        "UPDATE proactive_policy_settings SET revision=revision+1 "
        "WHERE subject_id='user:self'"
    )
    connection.commit()
    connection.close()
    bridge = ReadyBridge()

    result = asyncio.run(
        MemoryBackend(path, clock=lambda: NOW).proactive_scheduled_tick(bridge)
    )

    assert result == {
        "action": "skip", "reason": "configuration_changed_or_date_expired",
    }
    assert bridge.announcements == []
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT status,consumption_reason FROM proactive_schedule_overrides"
        ).fetchone() == ("consumed", "configuration_changed_or_date_expired")
        assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0
