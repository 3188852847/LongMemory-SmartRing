"""V31 圆屏反馈事件只关联明确、相邻且可追溯的问答。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_round_screen_memory_feedback_store import (
    SQLiteRoundScreenMemoryFeedbackStore,
)
from longmemory.adapters.storage.sqlite_round_screen_turn_store import (
    SQLiteRoundScreenTurnStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.methods.contracts import MemoryEvent


def test_v30_upgrade_adds_empty_round_screen_feedback_table(tmp_path):
    connection = open_database(tmp_path / "v30.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_round_screen_memory_feedback_target;
        DROP TABLE round_screen_memory_feedback_events;
        PRAGMA user_version=30;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM round_screen_memory_feedback_events"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_explicit_feedback_links_previous_completed_turn_without_copying_text(tmp_path):
    database = tmp_path / "feedback.db"
    now = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        ("previous-user", "user", "合成问题", now.isoformat()),
    )
    connection.commit()
    connection.close()
    SQLiteRoundScreenTurnStore(database, clock=lambda: now).record(
        user_message_id="previous-user", answer="合成回答",
        retrieved_l1_count=1, retrieved_l2_count=0, retrieved_l3_count=0,
    )
    feedback = MemoryEvent(
        "feedback-user", "user", "你刚才没想起来我说过的事情", now + timedelta(minutes=1),
    )
    connection = open_database(database)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        (feedback.event_id, feedback.role, feedback.content, feedback.occurred_at.isoformat()),
    )
    connection.commit()
    connection.close()

    result = SQLiteRoundScreenMemoryFeedbackStore(database).record_if_explicit(feedback)

    assert result is not None and result.recorded is True
    assert result.kind == "recall_miss" and result.target_user_message_id == "previous-user"
    connection = open_database(database)
    row = connection.execute(
        "SELECT target_user_message_id,feedback_message_id,event_kind,evidence_kind,"
        "interpreter_version FROM round_screen_memory_feedback_events"
    ).fetchone()
    columns = {item[1] for item in connection.execute(
        "PRAGMA table_info(round_screen_memory_feedback_events)"
    )}
    assert tuple(row) == (
        "previous-user", "feedback-user", "recall_miss",
        "explicit_round_screen_statement", "explicit_round_screen_feedback_v1",
    )
    assert "content" not in columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_explicit_feedback_does_not_link_stale_previous_turn(tmp_path):
    database = tmp_path / "stale.db"
    now = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
    connection = open_database(database)
    initialize_schema(connection)
    connection.executemany(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        [
            ("old-user", "user", "旧问题", now.isoformat()),
            ("feedback-user", "user", "你刚才记错了", (now + timedelta(minutes=11)).isoformat()),
        ],
    )
    connection.commit()
    connection.close()
    SQLiteRoundScreenTurnStore(database, clock=lambda: now).record(
        user_message_id="old-user", answer="旧回答",
        retrieved_l1_count=0, retrieved_l2_count=0, retrieved_l3_count=0,
    )
    event = MemoryEvent(
        "feedback-user", "user", "你刚才记错了", now + timedelta(minutes=11),
    )
    result = SQLiteRoundScreenMemoryFeedbackStore(database).record_if_explicit(event)
    assert result is not None and result.recorded is False
    assert result.reason == "previous_turn_too_old"
