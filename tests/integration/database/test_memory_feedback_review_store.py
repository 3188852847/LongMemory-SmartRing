"""V33 质量复核只追加元数据事件，并使用 revision 防止覆盖。"""

from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_memory_feedback_review_store import (
    SQLiteMemoryFeedbackReviewStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def test_v32_upgrade_adds_empty_review_event_table(tmp_path):
    connection = open_database(tmp_path / "v32.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_memory_feedback_review_target;
        DROP TABLE memory_feedback_review_events;
        PRAGMA user_version=32;
    """)
    initialize_schema(connection)
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(memory_feedback_review_events)"
    )}
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "content" not in columns and "reason_code" in columns
    assert connection.execute(
        "SELECT count(*) FROM memory_feedback_review_events"
    ).fetchone()[0] == 0
    connection.close()


def test_review_state_is_append_only_and_revision_guarded(tmp_path):
    database = tmp_path / "review.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.close()
    now = datetime(2026, 9, 10, 3, 0, tzinfo=UTC)
    store = SQLiteMemoryFeedbackReviewStore(database, clock=lambda: now)
    target = (("round_screen", "feedback-a", 1),)
    assert store.current(target)[target[0]]["state"] == "open"

    resolved = store.record(
        source="round_screen", target_id="feedback-a", feedback_revision=1,
        action="resolve", reason_code="memory_corrected", expected_review_revision=0,
    )
    assert resolved["state"] == "resolved" and resolved["review_revision"] == 1
    with pytest.raises(ValueError, match="memory_feedback_review_conflict"):
        store.record(
            source="round_screen", target_id="feedback-a", feedback_revision=1,
            action="reopen", reason_code="needs_follow_up", expected_review_revision=0,
        )
    reopened = store.record(
        source="round_screen", target_id="feedback-a", feedback_revision=1,
        action="reopen", reason_code="needs_follow_up", expected_review_revision=1,
    )
    assert reopened["state"] == "open" and reopened["review_revision"] == 2
    connection = open_database(database)
    rows = connection.execute(
        "SELECT action,reason_code,review_revision FROM memory_feedback_review_events "
        "ORDER BY review_revision"
    ).fetchall()
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(memory_feedback_review_events)"
    )}
    assert [tuple(row) for row in rows] == [
        ("resolve", "memory_corrected", 1),
        ("reopen", "needs_follow_up", 2),
    ]
    assert not {"question", "answer", "content"}.intersection(columns)
    connection.close()
