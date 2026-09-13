"""V42–V47 L2 影子账本保存判定与精确人工支持集。"""

from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_l2_sufficiency_shadow import (
    SQLiteL2SufficiencyShadowStore,
)
from longmemory.application.scenario_recall import (
    ScenarioRecallItem,
    ScenarioRecallResult,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceSufficiencyDecision,
    EvidenceSufficiencyReview,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def _source(database, message_id="user-a"):
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO conversation_messages(id,role,content,created_at) VALUES (?,?,?,?)",
        (message_id, "user", "我的猫是什么颜色", "2026-09-13T01:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def test_v41_upgrade_adds_empty_shadow_ledger(tmp_path):
    database = tmp_path / "v41.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute("DROP TABLE l2_sufficiency_shadow_review_supports")
    connection.execute("DROP TABLE l2_sufficiency_shadow_review_events")
    connection.execute("DROP TABLE l2_sufficiency_shadow_candidates")
    connection.execute("DROP TABLE l2_sufficiency_shadow_runs")
    connection.execute("PRAGMA user_version=41")
    connection.commit()
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM l2_sufficiency_shadow_runs"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v42_upgrade_adds_empty_owner_review_ledger(tmp_path):
    database = tmp_path / "v42.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute("DROP TABLE l2_sufficiency_shadow_review_supports")
    connection.execute("DROP TABLE l2_sufficiency_shadow_review_events")
    connection.execute("PRAGMA user_version=42")
    connection.commit()
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM l2_sufficiency_shadow_review_events"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v46_upgrade_adds_exact_l2_support_set_without_guessing_old_reviews(tmp_path):
    database = tmp_path / "v46.db"
    connection = open_database(database)
    initialize_schema(connection)
    connection.execute("DROP TABLE l2_sufficiency_shadow_review_supports")
    connection.execute(
        "ALTER TABLE l2_sufficiency_shadow_candidates DROP COLUMN content_characters"
    )
    connection.execute(
        "ALTER TABLE l2_sufficiency_shadow_review_events DROP COLUMN support_set_recorded"
    )
    connection.execute("PRAGMA user_version=46")
    connection.commit()

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    candidate_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(l2_sufficiency_shadow_candidates)"
        )
    }
    review_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(l2_sufficiency_shadow_review_events)"
        )
    }
    assert "content_characters" in candidate_columns
    assert "support_set_recorded" in review_columns
    assert connection.execute(
        "SELECT count(*) FROM l2_sufficiency_shadow_review_supports"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_shadow_store_records_snapshot_and_closed_decisions_without_text(tmp_path):
    database = tmp_path / "shadow.db"
    _source(database)
    now = datetime(2026, 9, 13, 1, 1, tzinfo=UTC)
    recalled = ScenarioRecallResult(
        "private context",
        (ScenarioRecallItem(
            "scene-cat", "猫咪", "用户养了一只叫豆包的猫。",
            ("l1-cat",), ("l0-cat",), keyword_score=2,
        ),),
    )
    store = SQLiteL2SufficiencyShadowStore(database)
    assert store.start(
        user_message_id="user-a", candidates=recalled,
        reviewer_version="gate-v1", prompt_sha256="a" * 64,
        provider="synthetic", model="synthetic-model", requested_at=now,
    ) is True
    assert store.start(
        user_message_id="user-a", candidates=recalled,
        reviewer_version="gate-v1", prompt_sha256="a" * 64,
        provider="synthetic", model="synthetic-model", requested_at=now,
    ) is False
    store.complete(
        user_message_id="user-a",
        review=EvidenceSufficiencyReview((EvidenceSufficiencyDecision(
            "scene-cat", False, "missing_attribute",
        ),), "gate-v1"),
        completed_at=now,
    )
    connection = open_database(database)
    run = connection.execute(
        "SELECT status,error_code FROM l2_sufficiency_shadow_runs"
    ).fetchone()
    candidate = connection.execute(
        "SELECT scenario_id,rank,keyword_score,supports_answer,reason_code,content_sha256 "
        "FROM l2_sufficiency_shadow_candidates"
    ).fetchone()
    assert tuple(run) == ("completed", None)
    assert tuple(candidate[:5]) == (
        "scene-cat", 1, 2, 0, "missing_attribute",
    )
    assert len(candidate[5]) == 64
    listing = store.list_recent(limit=10)
    assert listing["items"][0]["query"] == "我的猫是什么颜色"
    assert listing["items"][0]["candidate_count"] == 1
    assert listing["items"][0]["supported_count"] == 0
    detail = store.get("user-a")
    assert detail["query"] == "我的猫是什么颜色"
    assert detail["candidates"][0]["current_title"] is None
    assert detail["candidates"][0]["content_matches_snapshot"] is None
    assert detail["review"]["review_revision"] == 0
    review = store.review(
        user_message_id="user-a", verdict="correct", reason_code="agreement",
        expected_review_revision=0, expected_supported_scenario_ids=[],
    )
    assert review["review_revision"] == 1
    assert review["expected_supported_scenario_ids"] == []
    assert store.get("user-a")["review"]["verdict"] == "correct"
    assert store.get("user-a")["review"]["expected_supported_scenario_ids"] == []
    assert store.list_recent(limit=10)["items"][0]["review_verdict"] == "correct"
    assert store.list_recent(limit=10)["review_counts"] == {
        "completed": 1, "unreviewed": 0, "correct": 1,
        "incorrect": 0, "uncertain": 0,
    }
    metrics = store.list_recent(limit=10)["policy_metrics"]
    assert metrics["labeled_cases"] == 1
    assert metrics["unsupported_labeled_cases"] == 1
    assert metrics["unsupported_pass_cases"] == 0
    assert metrics["candidate_reduction_rate"] == 1
    assert metrics["readiness"]["policy_id"].startswith("l2-sufficiency-")
    try:
        store.review(
            user_message_id="user-a", verdict="incorrect",
            reason_code="missed_support", expected_review_revision=0,
            expected_supported_scenario_ids=["scene-cat"],
        )
    except ValueError as error:
        assert str(error) == "l2_sufficiency_shadow_review_conflict"
    else:
        raise AssertionError("stale review revision should fail")
    assert store.get("missing") is None
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(l2_sufficiency_shadow_candidates)"
    )}
    assert "content" not in columns and "query" not in columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()

    uncertain = store.review(
        user_message_id="user-a", verdict="uncertain",
        reason_code="ambiguous_query", expected_review_revision=1,
        expected_supported_scenario_ids=None,
    )
    assert uncertain["expected_supported_scenario_ids"] is None
    assert store.list_recent(limit=10)["policy_metrics"]["labeled_cases"] == 0


def test_shadow_store_completes_zero_candidate_observation_without_model_decision(tmp_path):
    database = tmp_path / "empty.db"
    _source(database)
    now = datetime(2026, 9, 13, 1, 2, tzinfo=UTC)
    store = SQLiteL2SufficiencyShadowStore(database)
    assert store.start(
        user_message_id="user-a", candidates=ScenarioRecallResult("", ()),
        reviewer_version="gate-v1", prompt_sha256="b" * 64,
        provider="synthetic", model="synthetic-model", requested_at=now,
    )
    store.complete_empty(user_message_id="user-a", completed_at=now)
    connection = open_database(database)
    assert connection.execute(
        "SELECT status FROM l2_sufficiency_shadow_runs"
    ).fetchone()[0] == "completed"
    assert connection.execute(
        "SELECT count(*) FROM l2_sufficiency_shadow_candidates"
    ).fetchone()[0] == 0
    connection.close()
