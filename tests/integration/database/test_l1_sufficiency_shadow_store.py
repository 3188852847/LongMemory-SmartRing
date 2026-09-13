"""V46 L1 影子账本保存机器判定与人工标注的精确支持集合。"""

from datetime import UTC, datetime

import pytest

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
from longmemory.infrastructure.database.migrations.v44_to_v45 import migrate as migrate_v44_to_v45
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
    connection.execute("DROP TABLE l1_sufficiency_shadow_review_supports")
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


def test_v45_review_migrates_as_legacy_label_without_inventing_support_set(tmp_path):
    database = tmp_path / "v45-review.db"
    _seed(database)
    connection = open_database(database)
    connection.execute("DROP TABLE l1_sufficiency_shadow_review_supports")
    connection.execute("DROP TABLE l1_sufficiency_shadow_review_events")
    connection.execute("DROP TABLE l1_sufficiency_shadow_candidates")
    connection.execute("DROP TABLE l1_sufficiency_shadow_runs")
    migrate_v44_to_v45(connection)
    connection.execute(
        "INSERT INTO l1_sufficiency_shadow_runs "
        "(user_message_id,retrieval_strategy,reviewer_version,prompt_sha256,provider,"
        "model,status,requested_at,completed_at) VALUES (?,?,?,?,?,?,'completed',?,?)",
        ("user-a", "keyword-v1", "gate-v1", "a" * 64, "synthetic", "synthetic",
         "2026-09-13T01:00:00+00:00", "2026-09-13T01:00:01+00:00"),
    )
    connection.execute(
        "INSERT INTO l1_sufficiency_shadow_review_events "
        "(id,user_message_id,review_revision,verdict,reason_code,occurred_at) "
        "VALUES (?,?,?,?,?,?)",
        ("review-old", "user-a", 1, "correct", "agreement",
         "2026-09-13T01:01:00+00:00"),
    )
    connection.execute("PRAGMA user_version=45")
    connection.commit()
    initialize_schema(connection)
    connection.close()

    review = SQLiteL1SufficiencyShadowStore(database).get("user-a")["review"]
    assert review["verdict"] == "correct"
    assert review["expected_supported_memory_ids"] is None
    metrics = SQLiteL1SufficiencyShadowStore(database).list_recent(limit=10)["policy_metrics"]
    assert metrics["reviewed_cases"] == 1
    assert metrics["labeled_cases"] == 0
    assert metrics["excluded_latest_reviews"] == 1


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
        "supports_answer,reason_code,content_sha256,content_characters "
        "FROM l1_sufficiency_shadow_candidates"
    ).fetchone()
    assert tuple(row[:7]) == (
        "memory-a", 1, 2, 0.75, 0.04, 0, "missing_attribute",
    )
    assert len(row[7]) == 64
    assert row[8] == len("用户养了一只叫豆包的猫。")
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
        expected_review_revision=0, expected_supported_memory_ids=[],
    )
    assert review["review_revision"] == 1
    assert review["expected_supported_memory_ids"] == []
    assert store.get("user-a")["review"]["expected_supported_memory_ids"] == []
    assert store.list_recent(limit=10)["review_counts"]["correct"] == 1

    corrected = store.review(
        user_message_id="user-a", verdict="incorrect",
        reason_code="missed_support", expected_review_revision=1,
        expected_supported_memory_ids=["memory-a"],
    )
    assert corrected["expected_supported_memory_ids"] == ["memory-a"]
    assert store.get("user-a")["review"]["expected_supported_memory_ids"] == ["memory-a"]
    metrics = store.list_recent(limit=10)["policy_metrics"]
    assert metrics["labeled_cases"] == 1
    assert metrics["false_block_cases"] == 1
    assert metrics["unsupported_pass_cases"] == 0
    assert metrics["original_candidate_count"] == 1
    assert metrics["kept_candidate_count"] == 0
    assert metrics["context_measured_cases"] == 1
    assert metrics["candidate_recall"] == 0

    with pytest.raises(ValueError, match="verdict_mismatch"):
        store.review(
            user_message_id="user-a", verdict="incorrect",
            reason_code="missed_support", expected_review_revision=2,
            expected_supported_memory_ids=[],
        )


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
