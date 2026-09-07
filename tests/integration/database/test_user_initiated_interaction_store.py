from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_conversation_store import (
    SQLiteConversationStore,
)
from longmemory.adapters.storage.sqlite_user_initiated_interaction_store import (
    DETECTOR_VERSION,
    SQLiteUserInitiatedInteractionStore,
)
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.bootstrap import build_memory_runtime
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


BASE = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)


def save_and_observe(connection, message_id, occurred_at):
    message = ConversationMessage(
        MessageId(message_id), MessageRole.USER,
        "私人原文不能复制到观察表。", occurred_at,
    )
    SQLiteConversationStore(connection).save(message)
    return SQLiteUserInitiatedInteractionStore(
        connection, id_factory=lambda: f"event-{message_id}",
    ).record_user_message(message)


def test_records_first_and_post_silence_user_messages_without_content(tmp_path):
    connection = open_database(tmp_path / "initiated.db")
    initialize_schema(connection)

    first = save_and_observe(connection, "first", BASE)
    too_soon = save_and_observe(connection, "soon", BASE + timedelta(hours=1))
    later = save_and_observe(connection, "later", BASE + timedelta(hours=5))

    assert first is not None and first.silence_gap_seconds is None
    assert too_soon is None
    assert later is not None and later.silence_gap_seconds == 4 * 3600
    assert later.detector_version == DETECTOR_VERSION
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(companion_user_initiated_interactions)"
    )}
    assert "content" not in columns
    assert connection.execute(
        "SELECT count(*) FROM companion_user_initiated_interactions"
    ).fetchone()[0] == 2
    connection.close()


def test_recent_outreach_excludes_message_from_user_initiated_evidence(tmp_path):
    connection = open_database(tmp_path / "recent-outreach.db")
    initialize_schema(connection)
    save_and_observe(connection, "first", BASE)
    queued_at = BASE + timedelta(hours=5)
    connection.execute(
        "INSERT INTO proactive_outreach "
        "(id,subject_id,trigger_kind,trigger_reason_code,content,created_at,"
        "scheduled_for,expires_at,state,state_changed_at,idempotency_key,revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("outreach", "user:self", "manual_test", "synthetic", "合成问候",
         queued_at.isoformat(), queued_at.isoformat(),
         (queued_at + timedelta(minutes=5)).isoformat(), "queued",
         queued_at.isoformat(), "synthetic-outreach", 2),
    )
    connection.execute(
        "INSERT INTO proactive_outreach_events VALUES (?,?,?,?,?,?,?,?)",
        ("created", "outreach", 1, None, "candidate", "created", "system_created",
         queued_at.isoformat()),
    )
    connection.execute(
        "INSERT INTO proactive_outreach_events VALUES (?,?,?,?,?,?,?,?)",
        ("queued", "outreach", 2, "candidate", "queued", "ready",
         "server_queue", queued_at.isoformat()),
    )
    connection.commit()

    excluded = save_and_observe(
        connection, "after-outreach", queued_at + timedelta(minutes=2),
    )

    assert excluded is None
    assert connection.execute(
        "SELECT count(*) FROM companion_user_initiated_interactions"
    ).fetchone()[0] == 1
    connection.close()


def test_v22_upgrade_adds_empty_user_initiated_table(tmp_path):
    connection = open_database(tmp_path / "v22.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_user_initiated_subject_recent;
        DROP TABLE companion_user_initiated_interactions;
        PRAGMA user_version=22;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_user_initiated_interactions"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_shared_runtime_records_web_or_round_screen_user_events(tmp_path):
    database = tmp_path / "runtime.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.close()
    times = iter((BASE, BASE + timedelta(hours=5)))
    runtime = build_memory_runtime(database, clock=lambda: next(times))

    runtime.prepare_user("我喜欢清淡的茶。")
    runtime.prepare_user("我今天想聊聊。")
    runtime.close()

    connection = open_database(database)
    rows = connection.execute(
        "SELECT occurred_at,silence_gap_seconds "
        "FROM companion_user_initiated_interactions ORDER BY occurred_at"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["silence_gap_seconds"] is None
    assert rows[1]["silence_gap_seconds"] == 5 * 3600
    connection.close()
