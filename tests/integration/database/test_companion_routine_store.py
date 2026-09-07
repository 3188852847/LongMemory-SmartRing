from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_companion_routine_store import (
    SQLiteCompanionRoutineCandidateStore,
)
from longmemory.application.companion_routine import (
    CompanionRoutineCandidateService,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


BASE = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)


def add_observation(connection, day):
    occurred = BASE + timedelta(days=day, minutes=day * 3)
    connection.execute(
        "INSERT INTO conversation_messages VALUES (?,?,?,?)",
        (f"message-{day}", "user", "合成私人原文", occurred.isoformat()),
    )
    connection.execute(
        "INSERT INTO companion_user_initiated_interactions VALUES (?,?,?,?,?,?,?,?)",
        (f"event-{day}", "user:self", f"message-{day}", occurred.isoformat(),
         (occurred - timedelta(hours=5)).isoformat(), 5 * 3600,
         "silence_gap_without_recent_outreach", "test-detector"),
    )


def test_persists_routine_sources_without_message_content_and_dismisses(tmp_path):
    connection = open_database(tmp_path / "routine.db")
    initialize_schema(connection)
    for day in range(3):
        add_observation(connection, day)
    connection.commit()
    store = SQLiteCompanionRoutineCandidateStore(connection)

    result = CompanionRoutineCandidateService(
        store, clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        id_factory=lambda: "routine-1",
    ).generate("user:self", utc_offset_minutes=480)

    assert result.outcome == "candidate_created"
    assert len(store.list_sources("routine-1")) == 3
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(companion_routine_candidate_sources)"
    )}
    assert "content" not in columns and "source_message_id" not in columns
    dismissed = store.dismiss(
        "routine-1", subject_id="user:self", expected_revision=1,
        now=datetime(2026, 9, 7, 1, tzinfo=UTC),
    )
    assert dismissed.status.value == "dismissed" and dismissed.revision == 2
    assert store.get_current("user:self") is None
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v23_upgrade_adds_empty_routine_candidate_tables(tmp_path):
    connection = open_database(tmp_path / "v23.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_routine_source_event;
        DROP TABLE companion_routine_candidate_sources;
        DROP INDEX idx_companion_routine_subject_recent;
        DROP INDEX idx_companion_routine_one_candidate;
        DROP TABLE companion_routine_candidates;
        PRAGMA user_version=23;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_routine_candidates"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
