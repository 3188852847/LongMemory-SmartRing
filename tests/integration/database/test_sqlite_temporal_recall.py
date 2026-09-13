import sqlite3

from longmemory.adapters.storage.sqlite_temporal_recall import (
    SQLiteTemporalRecallProvider,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


def test_expands_only_explicit_history_from_current_anchor(tmp_path):
    database = tmp_path / "temporal-recall.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.executemany(
        "INSERT INTO conversation_messages VALUES (?, 'user', ?, ?)",
        [("source-old", "我以前住在南京。", "2026-01-01T00:00:00+00:00"),
         ("source-new", "我五月搬到了合肥。", "2026-09-13T00:00:00+00:00")],
    )
    connection.executemany(
        "INSERT INTO atomic_memories "
        "(id,subject_id,content,recorded_at,valid_from,valid_to,retired_at,superseded_by_id) "
        "VALUES (?, 'user:self', ?, ?, ?, ?, ?, ?)",
        [("old-place", "用户住在南京。", "2026-01-01T00:00:00+00:00", None,
          None, None, None),
         ("new-place", "用户住在合肥。", "2026-09-13T00:00:00+00:00",
          "2026-05-01T00:00:00+00:00", None, None, None)],
    )
    connection.execute(
        "UPDATE atomic_memories SET valid_to=?, retired_at=?, superseded_by_id=? "
        "WHERE id='old-place'",
        ("2026-05-01T00:00:00+00:00", "2026-09-13T00:00:00+00:00", "new-place"),
    )
    connection.executemany(
        "INSERT INTO memory_evidence VALUES (?, ?, 'user_stated', ?)",
        [("old-place", "source-old", "2026-01-01T00:00:00+00:00"),
         ("new-place", "source-new", "2026-09-13T00:00:00+00:00")],
    )
    connection.commit()
    connection.close()
    provider = SQLiteTemporalRecallProvider(database)

    current = provider.recall("我现在住在哪里？", current_memory_ids=("new-place",))
    history = provider.recall("我以前住在哪里？", current_memory_ids=("new-place",))

    assert current.context == "" and current.items == ()
    assert [item.memory_id for item in history.items] == ["old-place"]
    assert history.items[0].source_message_ids == ("source-old",)
    assert "不代表现在仍然成立" in history.context
    with sqlite3.connect(database) as check:
        assert check.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 2
