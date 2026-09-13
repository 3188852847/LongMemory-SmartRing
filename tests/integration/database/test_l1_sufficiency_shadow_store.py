"""V45 L1 影子账本只存快照指纹、封闭判定和追加复核。"""

from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_l1_sufficiency_shadow import (
    SQLiteL1SufficiencyShadowStore,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision,
    EvidenceSufficiencyReview,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.methods.contracts import RetrievedTrace


def _seed(database):
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        ("user-a", "user", "我的猫是什么颜色", "2026-09-13T01:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO atomic_memories(id,subject_id,content,recorded_at) VALUES (?,?,?,?)",
        ("memory-a", "user:self", "用户养了一只叫豆包的猫。", "2026-09-13T01:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def test_v44_upgrade_adds_empty_l1_shadow_ledgers(tmp_path):
    database = tmp_path / "v44.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute("DROP TABLE l1_sufficiency_shadow_review_events")
    connection.execute("DROP TABLE l1_sufficiency_shadow_candidates")
    connection.execute("DROP TABLE l1_sufficiency_shadow_runs")
    connection.execute("PRAGMA user_version=44")
    connection.commit()
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM l1_sufficiency_shadow_runs"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_l1_shadow_store_records_scores_hashes_decisions_and_owner_review(tmp_path):
    database = tmp_path / "shadow.db"
    _seed(database)
    now = datetime(2026, 9, 13, 1, 1, tzinfo=UTC)
    candidate = RetrievedTrace(
        "memory-a", "用户养了一只叫豆包的猫。", ("l0-a",),
        keyword_score=2, dense_score=0.75, fused_score=0.04,
    )
    store = SQLiteL1SufficiencyShadowStore(database)
    assert store.start(
        user_message_id="user-a", candidates=(candidate,),
        retrieval_strategy="hybrid-v1", reviewer_version="gate-v1",
        prompt_sha256="a" * 64, provider="synthetic",
        model="synthetic-model", requested_at=now,
    )
    assert not store.start(
        user_message_id="user-a", candidates=(candidate,),
        retrieval_strategy="hybrid-v1", reviewer_version="gate-v1",
        prompt_sha256="a" * 64, provider="synthetic",
        model="synthetic-model", requested_at=now,
    )
    store.complete(
        user_message_id="user-a",
        review=EvidenceSufficiencyReview((EvidenceSufficiencyDecision(
            "memory-a", False, "missing_attribute",
        ),), "gate-v1"), completed_at=now,
    )
    connection = open_database(database)
    row = connection.execute(
        "SELECT memory_id,rank,keyword_score,dense_score,fused_score,"
        "supports_answer,reason_code,content_sha256 "
        "FROM l1_sufficiency_shadow_candidates"
    ).fetchone()
    assert tuple(row[:7]) == (
        "memory-a", 1, 2, 0.75, 0.04, 0, "missing_attribute",
    )
    assert len(row[7]) == 64
    columns = {item[1] for item in connection.execute(
        "PRAGMA table_info(l1_sufficiency_shadow_candidates)"
    )}
    assert "content" not in columns and "query" not in columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()

    listing = store.list_recent(limit=10)
    assert listing["items"][0]["query"] == "我的猫是什么颜色"
    assert listing["items"][0]["candidate_count"] == 1
    detail = store.get("user-a")
    assert detail["candidates"][0]["current_content"].endswith("豆包的猫。")
    assert detail["candidates"][0]["content_matches_snapshot"] is True
    review = store.review(
        user_message_id="user-a", verdict="correct", reason_code="agreement",
        expected_review_revision=0,
    )
    assert review["review_revision"] == 1
    assert store.list_recent(limit=10)["review_counts"]["correct"] == 1


def test_l1_shadow_empty_candidates_complete_without_decisions(tmp_path):
    database = tmp_path / "empty.db"
    _seed(database)
    now = datetime(2026, 9, 13, 1, 2, tzinfo=UTC)
    store = SQLiteL1SufficiencyShadowStore(database)
    assert store.start(
        user_message_id="user-a", candidates=(), retrieval_strategy="keyword-v1",
        reviewer_version="gate-v1", prompt_sha256="b" * 64,
        provider="synthetic", model="synthetic", requested_at=now,
    )
    store.complete_empty(user_message_id="user-a", completed_at=now)
    assert store.get("user-a")["status"] == "completed"
