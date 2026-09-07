from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_companion_strategy_store import (
    SQLiteCompanionStrategyCandidateStore,
)
from longmemory.application.companion_strategy import CompanionStrategyCandidateService
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


BASE = datetime(2026, 9, 1, 5, 2, tzinfo=UTC)


def add_observation(connection, day):
    queued = BASE + timedelta(days=day)
    observed = queued + timedelta(minutes=2)
    outreach = f"outreach-{day}"
    message = f"message-{day}"
    connection.execute(
        "INSERT INTO conversation_messages VALUES (?,?,?,?)",
        (message, "user", "合成测试消息", observed.isoformat()),
    )
    connection.execute(
        "INSERT INTO proactive_outreach "
        "(id,subject_id,trigger_kind,trigger_reason_code,content,created_at,"
        "scheduled_for,expires_at,state,state_changed_at,idempotency_key,revision) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (outreach, "user:self", "explicit_schedule", "scheduled_daily_greeting",
         "合成问候", queued.isoformat(), queued.isoformat(),
         (queued + timedelta(minutes=5)).isoformat(), "queued", queued.isoformat(),
         f"scheduled:{day}", 2),
    )
    connection.execute(
        "INSERT INTO proactive_outreach_events VALUES (?,?,?,?,?,?,?,?)",
        (f"created-{day}", outreach, 1, None, "candidate", "created",
         "system_created", queued.isoformat()),
    )
    connection.execute(
        "INSERT INTO proactive_outreach_events VALUES (?,?,?,?,?,?,?,?)",
        (f"queued-{day}", outreach, 2, "candidate", "queued", "ready",
         "server_queue", queued.isoformat()),
    )
    connection.execute(
        "INSERT INTO companion_interaction_events VALUES (?,?,?,?,?,?,?,?,?)",
        (f"interaction-{day}", "user:self", "subsequent_user_message_observed",
         outreach, message, observed.isoformat(), 120, "temporal_order", "test"),
    )


def test_persists_sources_without_message_body_and_dismisses_atomically(tmp_path):
    connection = open_database(tmp_path / "strategy.db")
    initialize_schema(connection)
    for day in range(3):
        add_observation(connection, day)
    connection.commit()
    store = SQLiteCompanionStrategyCandidateStore(connection)

    result = CompanionStrategyCandidateService(
        store, clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        id_factory=lambda: "candidate-1",
    ).generate("user:self", utc_offset_minutes=480)

    assert result.outcome == "candidate_created"
    assert len(store.list_sources("candidate-1")) == 3
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(companion_strategy_candidate_sources)"
    )}
    assert "content" not in columns and "source_message_id" not in columns
    dismissed = store.dismiss(
        "candidate-1", subject_id="user:self", expected_revision=1,
        now=datetime(2026, 9, 7, 1, tzinfo=UTC),
    )
    assert dismissed.status.value == "dismissed" and dismissed.revision == 2
    assert store.get_current("user:self") is None
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v21_upgrade_adds_empty_candidate_tables(tmp_path):
    connection = open_database(tmp_path / "v21.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_strategy_source_interaction;
        DROP TABLE companion_strategy_candidate_sources;
        DROP INDEX idx_companion_strategy_subject_recent;
        DROP INDEX idx_companion_strategy_one_candidate;
        DROP TABLE companion_strategy_candidates;
        PRAGMA user_version=21;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_strategy_candidates"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
