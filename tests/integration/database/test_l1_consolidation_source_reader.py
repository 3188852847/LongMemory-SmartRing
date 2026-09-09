"""L1 整理来源选择必须无游标缺口，并保留旧来源再成组机会。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_l1_consolidation_source_reader import (
    SQLiteL1ConsolidationSourceReader,
)
from longmemory.core.memory.consolidation.models import ConsolidationCursor
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


BASE = datetime(2026, 9, 1, tzinfo=UTC)


def add_l1(connection, number, *, scenario_status=None):
    moment = BASE + timedelta(days=number)
    memory_id, message_id = f"l1-{number:02}", f"l0-{number:02}"
    connection.execute(
        "INSERT INTO conversation_messages VALUES (?, 'user', ?, ?)",
        (message_id, f"用户原话 {number}", moment.isoformat()),
    )
    connection.execute(
        "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) VALUES (?,?,?,?)",
        (memory_id, "user:self", f"原子记忆 {number}", moment.isoformat()),
    )
    connection.execute(
        "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
        (memory_id, message_id, moment.isoformat()),
    )
    if scenario_status:
        scenario_id = f"l2-{number:02}"
        connection.execute(
            "INSERT INTO scenario_memories VALUES (?,?,?, ?,?,NULL,NULL,?,?,?,1)",
            (scenario_id, "user:self", "合成场景", "合成摘要", moment.isoformat(),
             scenario_status, "synthetic", "1"),
        )
        connection.execute(
            "INSERT INTO scenario_memory_sources VALUES (?,?,?,?)",
            (scenario_id, memory_id, f"原子记忆 {number}", moment.isoformat()),
        )
    return memory_id


def test_first_batch_takes_oldest_new_sources_without_skipping_cursor_range(tmp_path):
    connection = open_database(tmp_path / "sources.db")
    initialize_schema(connection)
    for number in range(1, 7):
        add_l1(connection, number)
    reader = SQLiteL1ConsolidationSourceReader(connection)
    first = reader.read_batch("user:self", after=None, limit=3)
    assert first.pending_new_source_count == 6
    assert [str(item.memory_id) for item in first.sources] == ["l1-01", "l1-02", "l1-03"]
    assert first.next_cursor.source_id == "l1-03"

    second = reader.read_batch("user:self", after=first.next_cursor, limit=3)
    assert second.pending_new_source_count == 3
    assert [str(item.memory_id) for item in second.sources] == ["l1-04", "l1-05", "l1-06"]
    assert second.next_cursor.source_id == "l1-06"
    connection.close()


def test_new_sources_are_supplemented_with_recent_old_ungrouped_context(tmp_path):
    connection = open_database(tmp_path / "context.db")
    initialize_schema(connection)
    for number in range(1, 6):
        add_l1(connection, number)
    cursor = ConsolidationCursor(BASE + timedelta(days=4), "l1-04")
    batch = SQLiteL1ConsolidationSourceReader(connection).read_batch(
        "user:self", after=cursor, limit=4,
    )
    assert batch.pending_new_source_count == 1
    assert batch.selected_new_source_count == 1
    assert [str(item.memory_id) for item in batch.sources] == [
        "l1-05", "l1-04", "l1-03", "l1-02",
    ]
    assert batch.next_cursor.source_id == "l1-05"
    connection.close()


def test_active_or_candidate_l2_sources_are_excluded_but_stale_sources_can_rebuild(tmp_path):
    connection = open_database(tmp_path / "status.db")
    initialize_schema(connection)
    add_l1(connection, 1, scenario_status="active")
    add_l1(connection, 2, scenario_status="candidate")
    add_l1(connection, 3, scenario_status="rejected")
    add_l1(connection, 4, scenario_status="stale")
    batch = SQLiteL1ConsolidationSourceReader(connection).read_batch(
        "user:self", after=None, limit=10,
    )
    assert [str(item.memory_id) for item in batch.sources] == ["l1-03", "l1-04"]
    connection.close()


def test_no_new_sources_does_not_reprocess_old_context_by_itself(tmp_path):
    connection = open_database(tmp_path / "empty.db")
    initialize_schema(connection)
    add_l1(connection, 1)
    cursor = ConsolidationCursor(BASE + timedelta(days=1), "l1-01")
    batch = SQLiteL1ConsolidationSourceReader(connection).read_batch(
        "user:self", after=cursor, limit=20,
    )
    assert batch.sources == () and batch.pending_new_source_count == 0
    assert batch.next_cursor is None
    connection.close()


def test_finite_l1_is_not_promoted_into_long_lived_scenario(tmp_path):
    connection = open_database(tmp_path / "temporary.db")
    initialize_schema(connection)
    memory_id = add_l1(connection, 1)
    connection.execute(
        "UPDATE atomic_memories SET valid_to=? WHERE id=?",
        ((BASE + timedelta(days=2)).isoformat(), memory_id),
    )
    connection.commit()

    batch = SQLiteL1ConsolidationSourceReader(connection).read_batch(
        "user:self", after=None, limit=20,
    )

    assert batch.sources == ()
    assert batch.pending_new_source_count == 0
    connection.close()
