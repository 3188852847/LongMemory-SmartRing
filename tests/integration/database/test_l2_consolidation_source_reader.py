"""L2→L3 来源只包含当前有效场景，并保留真实 L0 观察日。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_l2_consolidation_source_reader import (
    SQLiteL2ConsolidationSourceReader,
)
from longmemory.core.memory.consolidation.models import ConsolidationCursor
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


BASE = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)


def add_scenario(connection, number, *, status="active", valid_to=None):
    moment = BASE + timedelta(days=number)
    scenario_id = f"l2-{number:02}"
    memory_ids = []
    for suffix in ("a", "b"):
        memory_id, message_id = f"l1-{number:02}-{suffix}", f"l0-{number:02}-{suffix}"
        memory_ids.append(memory_id)
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,'user',?,?)",
            (message_id, f"原话 {number}-{suffix}", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
            "VALUES (?,'user:self',?,?)",
            (memory_id, f"事实 {number}-{suffix}", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
            (memory_id, message_id, moment.isoformat()),
        )
    connection.execute(
        "INSERT INTO scenario_memories VALUES (?,?,?, ?,?,NULL,?,?,?,?,1)",
        (scenario_id, "user:self", f"场景 {number}", f"摘要 {number}",
         moment.isoformat(), valid_to.isoformat() if valid_to else None,
         status, "synthetic", "1"),
    )
    connection.executemany(
        "INSERT INTO scenario_memory_sources VALUES (?,?,?,?)",
        ((scenario_id, memory_id, f"事实 {number}-{suffix}", moment.isoformat())
         for memory_id, suffix in zip(memory_ids, ("a", "b"), strict=True)),
    )


def test_l2_cursor_is_gap_free_and_sources_resolve_to_observation_days(tmp_path):
    connection = open_database(tmp_path / "l2-sources.db")
    initialize_schema(connection)
    for number in range(1, 5):
        add_scenario(connection, number)
    reader = SQLiteL2ConsolidationSourceReader(connection)
    first = reader.read_batch("user:self", after=None, limit=2, now=NOW)
    assert [str(item.scenario_id) for item in first.sources] == ["l2-01", "l2-02"]
    assert first.pending_new_source_count == 4
    assert first.next_cursor.source_id == "l2-02"
    assert first.sources[0].observation_days == ("2026-09-02",)
    assert first.sources[0].source_message_ids == ("l0-01-a", "l0-01-b")

    second = reader.read_batch("user:self", after=first.next_cursor, limit=3, now=NOW)
    assert [str(item.scenario_id) for item in second.sources] == [
        "l2-03", "l2-04", "l2-02",
    ]
    connection.close()


def test_inactive_or_expired_l2_never_enters_persona_batch(tmp_path):
    connection = open_database(tmp_path / "l2-filter.db")
    initialize_schema(connection)
    add_scenario(connection, 1, status="candidate")
    add_scenario(connection, 2, status="stale")
    add_scenario(connection, 3, valid_to=NOW - timedelta(days=1))
    add_scenario(connection, 4)
    batch = SQLiteL2ConsolidationSourceReader(connection).read_batch(
        "user:self", after=None, limit=10, now=NOW,
    )
    assert [str(item.scenario_id) for item in batch.sources] == ["l2-04"]
    assert batch.sources[0].content == "场景 4：摘要 4"
    connection.close()


def test_no_new_l2_does_not_replay_old_context_alone(tmp_path):
    connection = open_database(tmp_path / "l2-empty.db")
    initialize_schema(connection)
    add_scenario(connection, 1)
    cursor = ConsolidationCursor(BASE + timedelta(days=1), "l2-01")
    batch = SQLiteL2ConsolidationSourceReader(connection).read_batch(
        "user:self", after=cursor, limit=10, now=NOW,
    )
    assert batch.sources == () and batch.next_cursor is None
    connection.close()
