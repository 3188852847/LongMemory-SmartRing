"""V32 圆屏召回索引保存条目身份、顺序和指纹，不复制正文。"""

from datetime import UTC, datetime
import sqlite3

import pytest

from longmemory.adapters.storage.sqlite_round_screen_turn_store import (
    SQLiteRoundScreenTurnStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.infrastructure.database.migrations.v47_to_v48 import (
    migrate as migrate_v47_to_v48,
)


def test_v47_upgrade_adds_nullable_temporal_receipt_without_inventing_history():
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE round_screen_retrieval_evidence (
            user_message_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            item_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            keyword_score INTEGER,
            dense_score REAL,
            fused_score REAL
        );
        INSERT INTO round_screen_retrieval_evidence VALUES
            ('turn-old','l1','memory-old',1,
             'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
             2,0.7,0.03);
    """)

    migrate_v47_to_v48(connection)

    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(round_screen_retrieval_evidence)"
    )}
    assert {"temporal_role", "valid_from", "valid_to"} <= columns
    assert connection.execute(
        "SELECT temporal_role,valid_from,valid_to "
        "FROM round_screen_retrieval_evidence"
    ).fetchone() == (None, None, None)
    connection.close()


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


def test_v36_upgrade_adds_nullable_retrieval_scores_without_inventing_history(tmp_path):
    connection = open_database(tmp_path / "memory.db")
    initialize_schema(connection)
    connection.execute("PRAGMA user_version = 36")
    connection.execute("ALTER TABLE round_screen_retrieval_receipts RENAME TO old_receipts")
    connection.execute("ALTER TABLE round_screen_retrieval_evidence RENAME TO old_evidence")
    connection.executescript("""
        CREATE TABLE round_screen_retrieval_receipts (
            user_message_id TEXT PRIMARY KEY
        );
        CREATE TABLE round_screen_retrieval_evidence (
            user_message_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            item_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            PRIMARY KEY (user_message_id, layer, rank)
        );
    """)
    connection.execute("DROP TABLE old_evidence")
    connection.execute("DROP TABLE old_receipts")
    initialize_schema(connection)

    receipt_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(round_screen_retrieval_receipts)"
        )
    }
    evidence_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(round_screen_retrieval_evidence)"
        )
    }
    assert "retrieval_strategy" in receipt_columns
    assert {"keyword_score", "dense_score", "fused_score"} <= evidence_columns
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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
         "content_sha256": "a" * 64, "keyword_score": 2,
         "dense_score": 0.72, "fused_score": 0.031,
         "temporal_role": "historical", "valid_from": None,
         "valid_to": "2026-05-01T00:00:00+00:00"},
        {"layer": "l2", "item_id": "scenario-a", "rank": 1,
         "content_sha256": "b" * 64, "keyword_score": 3,
         "dense_score": None, "fused_score": None},
    )
    store = SQLiteRoundScreenTurnStore(database, clock=lambda: now)
    created = store.record(
        user_message_id="user-turn", answer="合成回答",
        retrieved_l1_count=1, retrieved_l2_count=1, retrieved_l3_count=0,
        retrieval_evidence=evidence, retrieval_strategy="keyword_dense_rrf_v1",
    )
    replay = store.record(
        user_message_id="user-turn", answer="合成回答",
        retrieved_l1_count=1, retrieved_l2_count=1, retrieved_l3_count=0,
        retrieval_evidence=evidence, retrieval_strategy="keyword_dense_rrf_v1",
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
        "SELECT user_message_id,retrieval_strategy FROM round_screen_retrieval_receipts"
    ).fetchone()[:] == ("user-turn", "keyword_dense_rrf_v1")
    scores = connection.execute(
        "SELECT keyword_score,dense_score,fused_score FROM "
        "round_screen_retrieval_evidence WHERE layer='l1'"
    ).fetchone()
    assert tuple(scores) == (2, 0.72, 0.031)
    temporal = connection.execute(
        "SELECT temporal_role,valid_from,valid_to FROM "
        "round_screen_retrieval_evidence WHERE layer='l1'"
    ).fetchone()
    assert tuple(temporal) == (
        "historical", None, "2026-05-01T00:00:00+00:00",
    )
    l2_scores = connection.execute(
        "SELECT keyword_score,dense_score,fused_score FROM "
        "round_screen_retrieval_evidence WHERE layer='l2'"
    ).fetchone()
    assert tuple(l2_scores) == (3, None, None)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
    with pytest.raises(ValueError, match="round_screen_retrieval_evidence_invalid"):
        store.record(
            user_message_id="another", answer="无效",
            retrieved_l1_count=2, retrieved_l2_count=0, retrieved_l3_count=0,
            retrieval_evidence=evidence[:1],
        )


@pytest.mark.parametrize("layer,temporal_role,valid_to", [
    ("l1", "historical", "2026-05-01T00:00:00"),
    ("l2", "historical", "2026-05-01T00:00:00+00:00"),
    ("l1", None, "2026-05-01T00:00:00+00:00"),
])
def test_temporal_receipt_rejects_ambiguous_or_non_l1_metadata(
    tmp_path, layer, temporal_role, valid_to,
):
    store = SQLiteRoundScreenTurnStore(tmp_path / "not-opened.db")
    evidence = ({
        "layer": layer,
        "item_id": "item-a",
        "rank": 1,
        "content_sha256": "a" * 64,
        "keyword_score": None,
        "dense_score": None,
        "fused_score": None,
        "temporal_role": temporal_role,
        "valid_from": None,
        "valid_to": valid_to,
    },)
    counts = {"l1": 0, "l2": 0, "l3": 0}
    counts[layer] = 1

    with pytest.raises(ValueError, match="round_screen_retrieval_evidence_invalid"):
        store.record(
            user_message_id="unused", answer="unused",
            retrieved_l1_count=counts["l1"],
            retrieved_l2_count=counts["l2"],
            retrieved_l3_count=counts["l3"],
            retrieval_evidence=evidence,
        )
