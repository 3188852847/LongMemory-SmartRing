"""V42 L2 证据充分性影子账本只保存引用、指纹和封闭判定。"""

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
    assert store.get("missing") is None
    columns = {row[1] for row in connection.execute(
        "PRAGMA table_info(l2_sufficiency_shadow_candidates)"
    )}
    assert "content" not in columns and "query" not in columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


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
