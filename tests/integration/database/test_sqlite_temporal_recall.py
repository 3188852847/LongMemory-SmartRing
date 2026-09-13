import sqlite3
from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_temporal_recall import (
    SQLiteTemporalRecallProvider,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


@pytest.fixture
def temporal_database(tmp_path):
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
    return database


def test_expands_only_explicit_history_from_current_anchor(temporal_database):
    database = temporal_database
    provider = SQLiteTemporalRecallProvider(database)

    current = provider.recall("我现在住在哪里？", current_memory_ids=("new-place",))
    history = provider.recall("我以前住在哪里？", current_memory_ids=("new-place",))

    assert current.context == "" and current.items == ()
    assert [item.memory_id for item in history.items] == ["old-place"]
    assert history.items[0].source_message_ids == ("source-old",)
    assert "不代表现在仍然成立" in history.context
    with sqlite3.connect(database) as check:
        assert check.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 2


def test_retired_anchor_cannot_label_current_successor_as_historical(temporal_database):
    result = SQLiteTemporalRecallProvider(temporal_database).recall(
        "我以前住在哪里？", current_memory_ids=("old-place",),
    )
    assert result.items == ()
    assert result.context == ""


@pytest.mark.parametrize("field,value", [
    ("retired_at", "2026-09-12T00:00:00+00:00"),
    ("valid_to", "2026-09-13T00:00:00+00:00"),
    ("valid_from", "2026-09-14T00:00:00+00:00"),
])
def test_rechecks_anchor_lifecycle_and_effective_time(temporal_database, field, value):
    with sqlite3.connect(temporal_database) as connection:
        connection.execute(f"UPDATE atomic_memories SET {field}=? WHERE id='new-place'", (value,))
        if field == "valid_from":
            # 仍保留精确变化边，确保停止来自锚点尚未生效，而非恰巧断链。
            connection.execute("UPDATE atomic_memories SET valid_to=? WHERE id='old-place'", (value,))
    provider = SQLiteTemporalRecallProvider(
        temporal_database, clock=lambda: datetime(2026, 9, 13, tzinfo=UTC),
    )
    assert provider.recall("我以前住在哪里？", current_memory_ids=("new-place",)).items == ()


def test_history_and_evidence_share_one_read_snapshot(temporal_database, monkeypatch):
    from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore

    with sqlite3.connect(temporal_database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    original = SQLiteMemoryStore.list_all

    def read_then_delete(store):
        memories = original(store)
        # 第二个连接模拟管理入口在内容读取后删除来源关联。
        with sqlite3.connect(temporal_database) as writer:
            writer.execute("DELETE FROM memory_evidence WHERE memory_id='old-place'")
        return memories

    monkeypatch.setattr(SQLiteMemoryStore, "list_all", read_then_delete)
    result = SQLiteTemporalRecallProvider(temporal_database).recall(
        "我以前住在哪里？", current_memory_ids=("new-place",),
    )
    assert result.items[0].source_message_ids == ("source-old",)
    with sqlite3.connect(temporal_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM memory_evidence WHERE memory_id='old-place'",
        ).fetchone()[0] == 0


@pytest.mark.parametrize("at,expected", [
    (datetime(2026, 4, 30, tzinfo=UTC), ()),
    (datetime(2026, 5, 1, tzinfo=UTC), ("old-place",)),
])
def test_anchor_valid_from_is_inclusive(temporal_database, at, expected):
    provider = SQLiteTemporalRecallProvider(temporal_database, clock=lambda: at)
    result = provider.recall("我以前住在哪里？", current_memory_ids=("new-place",))
    assert tuple(item.memory_id for item in result.items) == expected


@pytest.mark.parametrize("query,anchors", [
    ("", ("new-place",)),
    ("我以前住在南京。今天吃什么？", ("new-place",)),
    ("我以前住在哪里？", ()),
])
def test_closed_gate_does_not_open_database(tmp_path, query, anchors):
    database = tmp_path / "must-not-exist.db"
    result = SQLiteTemporalRecallProvider(database).recall(query, current_memory_ids=anchors)
    assert result.context == "" and result.items == ()
    assert not database.exists()
