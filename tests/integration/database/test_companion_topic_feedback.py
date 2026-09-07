from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_natural_memory_commands import (
    SQLiteNaturalMemoryCommandHandler,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.core.proactive import OutreachEvidence, OutreachState, OutreachTrigger
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.methods.contracts import MemoryEvent
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.bootstrap import build_memory_runtime


NOW = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)


def _prepare_recent_topic(database):
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO scenario_memories "
        "(id,subject_id,title,summary,generated_at,status,generator_name,"
        "generator_version,revision) VALUES (?,?,?,?,?,?,?,?,?)",
        ("scenario-1", "user:self", "毕业设计", "用户正在准备毕业设计。",
         NOW.isoformat(), "active", "synthetic", "1", 1),
    )
    connection.execute(
        "INSERT INTO proactive_topic_seeds VALUES (?,?,?,?,?,?,?,?)",
        ("topic-1", "user:self", "scenario-1", "毕业设计准备得怎么样了？",
         "active", NOW.isoformat(), NOW.isoformat(), 1),
    )
    connection.commit()
    ids = iter(("outreach-1", "outreach-created-1", "outreach-queued-1"))
    ledger = ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection),
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    outreach = ledger.create_candidate(
        subject_id="user:self",
        trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
        trigger_reason_code="scheduled_memory_topic",
        content="毕业设计准备得怎么样了？",
        scheduled_for=NOW,
        expires_at=NOW + timedelta(minutes=5),
        idempotency_key="schedule-1",
        topic_seed_id="topic-1",
        topic_seed_revision=1,
    )
    ledger.record_transition(
        outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="ready", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    connection.close()


def test_explicit_rejection_disables_recent_topic_and_preserves_audit(tmp_path):
    database = tmp_path / "feedback.db"
    _prepare_recent_topic(database)
    handler = SQLiteNaturalMemoryCommandHandler(database)

    result = handler.handle(MemoryEvent(
        "message-reject", "user", "以后不要主动聊这个话题。",
        NOW + timedelta(minutes=3),
    ))
    handler.close()

    assert result.kind == "reject_proactive_topic"
    assert result.status == "applied"
    connection = open_database(database)
    assert tuple(connection.execute(
        "SELECT status,revision FROM proactive_topic_seeds WHERE id='topic-1'"
    ).fetchone()) == ("disabled", 2)
    feedback = connection.execute(
        "SELECT outreach_id,topic_seed_id,source_message_id,feedback_kind,"
        "action_kind,evidence_kind FROM companion_feedback_events"
    ).fetchone()
    assert tuple(feedback) == (
        "outreach-1", "topic-1", "message-reject", "reject_topic",
        "topic_seed_disabled", "user_explicit",
    )
    assert connection.execute(
        "SELECT content FROM conversation_messages WHERE id='message-reject'"
    ).fetchone()[0] == "以后不要主动聊这个话题。"
    # 同一条明确反馈也是问候后的首条用户消息，但两个事件语义保持分离。
    assert connection.execute(
        "SELECT count(*) FROM companion_interaction_events "
        "WHERE source_message_id='message-reject'"
    ).fetchone()[0] == 1
    connection.close()
    history = MemoryBackend(database).proactive_history(limit=10)["items"][0]
    assert history["explicit_feedback"]["feedback_kind"] == "reject_topic"
    assert history["explicit_feedback"]["evidence_kind"] == "user_explicit"


def test_rejection_without_recent_topic_changes_nothing_but_keeps_l0(tmp_path):
    database = tmp_path / "no-target.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.close()
    handler = SQLiteNaturalMemoryCommandHandler(database)

    result = handler.handle(MemoryEvent(
        "message-no-target", "user", "别再主动聊这个话题", NOW,
    ))
    handler.close()

    assert result.status == "target_not_found"
    connection = open_database(database)
    assert connection.execute(
        "SELECT count(*) FROM companion_feedback_events"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM conversation_messages WHERE id='message-no-target'"
    ).fetchone()[0] == 1
    connection.close()


def test_v20_upgrade_adds_empty_feedback_table(tmp_path):
    connection = open_database(tmp_path / "v20.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_feedback_subject_recent;
        DROP TABLE companion_feedback_events;
        PRAGMA user_version=20;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_feedback_events"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_topic_rejection_still_works_when_l1_writes_are_paused(tmp_path):
    database = tmp_path / "paused-l1.db"
    _prepare_recent_topic(database)
    runtime = build_memory_runtime(
        database, clock=lambda: NOW + timedelta(minutes=3),
    )
    runtime.configure(write_enabled=False, use_enabled=True)

    result = runtime.prepare_user("不要再主动聊这个话题")
    runtime.close()

    assert result.memory_command is not None
    assert result.memory_command.status == "applied"
    connection = open_database(database)
    assert connection.execute(
        "SELECT status FROM proactive_topic_seeds WHERE id='topic-1'"
    ).fetchone()[0] == "disabled"
    connection.close()
