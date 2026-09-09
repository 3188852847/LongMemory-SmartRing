"""V32 圆屏召回索引保存条目身份、顺序和指纹，不复制正文。"""

from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_round_screen_turn_store import (
    SQLiteRoundScreenTurnStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def test_v31_upgrade_adds_empty_round_screen_retrieval_evidence_table(tmp_path):
    connection = open_database(tmp_path / "v31.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_round_screen_retrieval_item;
        DROP TABLE round_screen_retrieval_evidence;
        DROP TABLE round_screen_retrieval_receipts;
        PRAGMA user_version=31;
    """)
    initialize_schema(connection)
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(round_screen_retrieval_evidence)"
    )}
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "content" not in columns and "content_sha256" in columns
    assert connection.execute(
        "SELECT count(*) FROM round_screen_retrieval_receipts"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_turn_receipt_atomically_records_ranked_evidence_and_rejects_conflict(tmp_path):
    database = tmp_path / "evidence.db"
    now = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        ("user-turn", "user", "合成问题", now.isoformat()),
    )
    connection.commit()
    connection.close()
    evidence = (
        {"layer": "l1", "item_id": "memory-a", "rank": 1,
         "content_sha256": "a" * 64},
        {"layer": "l2", "item_id": "scenario-a", "rank": 1,
         "content_sha256": "b" * 64},
    )
    store = SQLiteRoundScreenTurnStore(database, clock=lambda: now)
    created = store.record(
        user_message_id="user-turn", answer="合成回答",
        retrieved_l1_count=1, retrieved_l2_count=1, retrieved_l3_count=0,
        retrieval_evidence=evidence,
    )
    replay = store.record(
        user_message_id="user-turn", answer="合成回答",
        retrieved_l1_count=1, retrieved_l2_count=1, retrieved_l3_count=0,
        retrieval_evidence=evidence,
    )
    assert created.created is True and replay.created is False
    connection = open_database(database)
    rows = connection.execute(
        "SELECT layer,item_id,rank,content_sha256 FROM round_screen_retrieval_evidence "
        "ORDER BY layer,rank"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("l1", "memory-a", 1, "a" * 64),
        ("l2", "scenario-a", 1, "b" * 64),
    ]
    assert connection.execute(
        "SELECT user_message_id FROM round_screen_retrieval_receipts"
    ).fetchone()[0] == "user-turn"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
    with pytest.raises(ValueError, match="round_screen_retrieval_evidence_invalid"):
        store.record(
            user_message_id="another", answer="无效",
            retrieved_l1_count=2, retrieved_l2_count=0, retrieved_l3_count=0,
            retrieval_evidence=evidence[:1],
        )
