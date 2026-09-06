"""V11 低频整理账本的持久化、互斥、游标与预算回归。"""

from datetime import UTC, datetime, timedelta

import pytest

from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationCursor,
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


START = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def running(run_id="run-1", stage=ConsolidationStage.L1_TO_L2):
    return ConsolidationRun(
        run_id, "user:self", stage, ConsolidationTrigger.NEW_EVIDENCE,
        ConsolidationRunStatus.RUNNING, START,
    )


def test_run_survives_reopen_and_completed_cursor_advances(tmp_path):
    path = tmp_path / "ledger.db"
    connection = open_database(path)
    initialize_schema(connection)
    store = SQLiteConsolidationRunStore(connection)
    store.start(running())
    store.finish(ConsolidationRun(
        "run-1", "user:self", ConsolidationStage.L1_TO_L2,
        ConsolidationTrigger.NEW_EVIDENCE, ConsolidationRunStatus.COMPLETED,
        START, source_count=6, model_call_count=1,
        finished_at=START + timedelta(seconds=8), outcome_code="candidate_created",
        cursor=ConsolidationCursor(START - timedelta(minutes=1), "l1-last"),
    ))
    connection.close()
    connection = open_database(path)
    store = SQLiteConsolidationRunStore(connection)
    recent = store.list_recent("user:self", ConsolidationStage.L1_TO_L2)
    assert len(recent) == 1 and recent[0].status == ConsolidationRunStatus.COMPLETED
    assert store.latest_cursor("user:self", ConsolidationStage.L1_TO_L2).source_id == "l1-last"
    assert store.model_calls_since(
        "user:self", ConsolidationStage.L1_TO_L2, START - timedelta(days=1)
    ) == 1
    assert store.has_running("user:self", ConsolidationStage.L1_TO_L2) is False
    connection.close()


def test_only_one_running_job_per_subject_and_stage(tmp_path):
    connection = open_database(tmp_path / "exclusive.db")
    initialize_schema(connection)
    store = SQLiteConsolidationRunStore(connection)
    store.start(running())
    with pytest.raises(ValueError, match="consolidation_already_running"):
        store.start(running("run-2"))
    # 不同阶段可以独立运行，避免 L1→L2 账本阻塞 L2→L3。
    store.start(running("run-3", ConsolidationStage.L2_TO_L3))
    assert store.has_running("user:self", ConsolidationStage.L2_TO_L3)
    connection.close()


def test_failed_run_is_audited_without_advancing_cursor(tmp_path):
    connection = open_database(tmp_path / "failed.db")
    initialize_schema(connection)
    store = SQLiteConsolidationRunStore(connection)
    store.start(running())
    store.finish(ConsolidationRun(
        "run-1", "user:self", ConsolidationStage.L1_TO_L2,
        ConsolidationTrigger.NEW_EVIDENCE, ConsolidationRunStatus.FAILED,
        START, source_count=4, model_call_count=1,
        finished_at=START + timedelta(seconds=3), outcome_code="model_request_failed",
    ))
    assert store.latest_cursor("user:self", ConsolidationStage.L1_TO_L2) is None
    assert store.list_recent("user:self", ConsolidationStage.L1_TO_L2)[0].outcome_code == (
        "model_request_failed"
    )
    connection.close()


def test_v10_upgrade_adds_empty_ledger_without_changing_existing_memory(tmp_path):
    connection = open_database(tmp_path / "v10.db")
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
        "VALUES ('l1-existing','user:self','用户喜欢乌龙茶。',?)",
        (START.isoformat(),),
    )
    connection.executescript("""
        DROP INDEX idx_consolidation_recent;
        DROP INDEX idx_consolidation_one_running;
        DROP TABLE memory_consolidation_runs;
        PRAGMA user_version=10;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT content FROM atomic_memories WHERE id='l1-existing'"
    ).fetchone()[0] == "用户喜欢乌龙茶。"
    assert connection.execute("SELECT count(*) FROM memory_consolidation_runs").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
