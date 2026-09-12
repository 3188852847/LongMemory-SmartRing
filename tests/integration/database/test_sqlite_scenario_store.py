"""L2 场景事务、来源门槛与生命周期只使用合成 V6 数据库。"""

from datetime import UTC, datetime
import sqlite3

import pytest

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.adapters.storage.sqlite_scenario_recall import SQLiteScenarioRecallProvider
from longmemory.application.scenario_management.service import ScenarioManagementService
from longmemory.core.common.identifiers import (
    MemoryId,
    MessageId,
    ScenarioAuditId,
    ScenarioId,
    ScenarioLifecycleEventId,
    ScenarioReviewId,
)
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    CURRENT_USER_SUBJECT_ID,
    MemoryEvidence,
    MemorySourceType,
)
from longmemory.core.memory.l2_scenario.models import (
    ScenarioGenerationAudit,
    ScenarioLifecycleAction,
    ScenarioLifecycleActor,
    ScenarioLifecycleEvent,
    ScenarioMemory,
    ScenarioReview,
    ScenarioReviewDecision,
    ScenarioSource,
    ScenarioStatus,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)


def _database(tmp_path):
    connection = open_database(tmp_path / "l2.db")
    initialize_schema(connection)
    return connection


def _save_l1(connection, memory_id: str, message_id: str, content: str) -> None:
    message = ConversationMessage(MessageId(message_id), MessageRole.USER, content, NOW)
    memory = AtomicMemory(MemoryId(memory_id), CURRENT_USER_SUBJECT_ID, content, NOW)
    SQLiteConversationStore(connection).save(message)
    SQLiteMemoryStore(connection).save(memory, MemoryEvidence(
        memory.id, message.id, MemorySourceType.USER_STATED, NOW
    ))


def _candidate():
    scenario = ScenarioMemory(
        ScenarioId("scenario-1"), CURRENT_USER_SUBJECT_ID, "准备答辩",
        "用户本周正在准备周五的答辩，主要任务是修改 PPT。", NOW,
        ScenarioStatus.CANDIDATE, "synthetic", "1",
    )
    sources = (
        ScenarioSource(scenario.id, MemoryId("l1-a"), "用户周五要答辩。", NOW),
        ScenarioSource(scenario.id, MemoryId("l1-b"), "用户正在修改 PPT。", NOW),
    )
    audit = ScenarioGenerationAudit(
        ScenarioAuditId("audit-1"), scenario.id, "synthetic", "1", NOW, 2, 2
    )
    return scenario, sources, audit


def test_candidate_sources_audit_and_review_are_persisted_atomically(tmp_path):
    connection = _database(tmp_path)
    _save_l1(connection, "l1-a", "l0-a", "用户周五要答辩。")
    _save_l1(connection, "l1-b", "l0-b", "用户正在修改 PPT。")
    store = SQLiteScenarioStore(connection)
    scenario, sources, audit = _candidate()

    store.save_candidate(scenario, sources, audit)
    assert store.get(scenario.id) == scenario
    assert store.list_sources(scenario.id) == sources
    assert connection.execute("SELECT count(*) FROM scenario_generation_audits").fetchone()[0] == 1

    accepted = store.review(ScenarioReview(
        ScenarioReviewId("review-1"), scenario.id,
        ScenarioReviewDecision.ACCEPTED, NOW, 1,
    ), expected_revision=1)
    assert accepted.status == ScenarioStatus.ACTIVE
    assert accepted.revision == 2
    assert store.list_sources(scenario.id) == sources
    with pytest.raises(ValueError, match="scenario_review_conflict"):
        store.review(ScenarioReview(
            ScenarioReviewId("review-2"), scenario.id,
            ScenarioReviewDecision.REJECTED, NOW, 2,
        ), expected_revision=2)
    connection.close()


def test_active_scenario_can_be_ended_once_with_audited_event(tmp_path):
    """手动结束保留来源，并把时间、状态、修订和事件作为一个事务保存。"""

    connection = _database(tmp_path)
    _save_l1(connection, "l1-a", "l0-a", "用户周五要答辩。")
    _save_l1(connection, "l1-b", "l0-b", "用户正在修改 PPT。")
    store = SQLiteScenarioStore(connection)
    scenario, sources, audit = _candidate()
    store.save_candidate(scenario, sources, audit)
    store.review(ScenarioReview(
        ScenarioReviewId("review-1"), scenario.id,
        ScenarioReviewDecision.ACCEPTED, NOW, 1,
    ), expected_revision=1)
    ended_at = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
    event = ScenarioLifecycleEvent(
        ScenarioLifecycleEventId("lifecycle-1"), scenario.id,
        ScenarioLifecycleAction.MANUAL_END, ScenarioLifecycleActor.USER,
        ended_at, ScenarioStatus.ACTIVE, ScenarioStatus.STALE, 3,
    )

    ended = store.end(event, expected_revision=2)

    assert ended.status == ScenarioStatus.STALE
    assert ended.valid_to == ended_at
    assert ended.revision == 3
    assert store.list_sources(scenario.id) == sources
    assert store.list_lifecycle_events(scenario.id) == (event,)
    with pytest.raises(ValueError, match="scenario_lifecycle_conflict"):
        store.end(ScenarioLifecycleEvent(
            ScenarioLifecycleEventId("lifecycle-2"), scenario.id,
            ScenarioLifecycleAction.MANUAL_END, ScenarioLifecycleActor.USER,
            ended_at, ScenarioStatus.ACTIVE, ScenarioStatus.STALE, 4,
        ), expected_revision=3)
    assert store.list_lifecycle_events(scenario.id) == (event,)
    connection.close()


def test_only_relevant_accepted_scenario_is_recalled_with_full_provenance(tmp_path):
    connection = _database(tmp_path)
    _save_l1(connection, "l1-a", "l0-a", "用户周五要答辩。")
    _save_l1(connection, "l1-b", "l0-b", "用户正在修改 PPT。")
    store = SQLiteScenarioStore(connection)
    scenario, sources, audit = _candidate()
    store.save_candidate(scenario, sources, audit)

    # candidate 尚未被用户接受，即使关键词相关也不能参与回答。
    provider = SQLiteScenarioRecallProvider(tmp_path / "l2.db")
    assert provider.recall("答辩准备得怎么样").items == ()

    store.review(ScenarioReview(
        ScenarioReviewId("review-1"), scenario.id,
        ScenarioReviewDecision.ACCEPTED, NOW, 1,
    ), expected_revision=1)
    result = provider.recall("答辩准备得怎么样")
    assert len(result.items) == 1
    assert result.items[0].scenario_id == "scenario-1"
    assert result.items[0].source_memory_ids == ("l1-a", "l1-b")
    assert result.items[0].source_message_ids == ("l0-a", "l0-b")
    assert result.items[0].keyword_score == 4
    assert "已经复核或策略门控" in result.context
    assert provider.recall("我的猫叫什么").items == ()
    connection.execute(
        "UPDATE scenario_memories SET valid_to=? WHERE id=?",
        (datetime(2020, 1, 1, tzinfo=UTC).isoformat(), "scenario-1"),
    )
    connection.commit()
    assert provider.recall("答辩准备得怎么样").items == ()
    connection.execute(
        "UPDATE scenario_memories SET valid_to=NULL, status='stale' WHERE id=?",
        ("scenario-1",),
    )
    connection.commit()
    assert provider.recall("答辩准备得怎么样").items == ()
    connection.close()


def test_two_l1_from_one_user_message_are_rejected_without_partial_rows(tmp_path):
    connection = _database(tmp_path)
    message = ConversationMessage(
        MessageId("one-l0"), MessageRole.USER,
        "我周五要答辩，这几天在修改 PPT。", NOW,
    )
    SQLiteConversationStore(connection).save(message)
    l1_store = SQLiteMemoryStore(connection)
    for memory_id, content in (("l1-a", "用户周五要答辩。"), ("l1-b", "用户正在修改 PPT。")):
        memory = AtomicMemory(MemoryId(memory_id), CURRENT_USER_SUBJECT_ID, content, NOW)
        l1_store.save(memory, MemoryEvidence(
            memory.id, message.id, MemorySourceType.USER_STATED, NOW
        ))
    store = SQLiteScenarioStore(connection)
    scenario, sources, audit = _candidate()

    with pytest.raises(ValueError, match="scenario_requires_distinct_user_l0_sources"):
        store.save_candidate(scenario, sources, audit)
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM scenario_memory_sources").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM scenario_generation_audits").fetchone()[0] == 0
    connection.close()


def test_audit_insert_failure_rolls_back_candidate_and_sources(tmp_path):
    connection = _database(tmp_path)
    _save_l1(connection, "l1-a", "l0-a", "用户周五要答辩。")
    _save_l1(connection, "l1-b", "l0-b", "用户正在修改 PPT。")
    scenario, sources, audit = _candidate()
    # 人工放入重复审计 ID，使保存流程在最后一步失败，验证前两步回滚。
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("INSERT INTO scenario_generation_audits VALUES "
                       "('audit-1', 'occupied', 'x', '1', ?, 2, 2)", (NOW.isoformat(),))
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(sqlite3.IntegrityError):
        SQLiteScenarioStore(connection).save_candidate(scenario, sources, audit)
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM scenario_memory_sources").fetchone()[0] == 0
    connection.close()


def test_application_service_creates_reviewable_candidate_without_using_it(tmp_path):
    """应用用例生成 candidate 并接受复核，但不接触聊天召回。"""

    connection = _database(tmp_path)
    _save_l1(connection, "l1-a", "l0-a", "用户周五要答辩。")
    _save_l1(connection, "l1-b", "l0-b", "用户正在修改 PPT。")
    l1_store = SQLiteMemoryStore(connection)
    l2_store = SQLiteScenarioStore(connection)
    service = ScenarioManagementService(memory_store=l1_store, scenario_store=l2_store)

    candidate = service.create_candidate(
        title="准备答辩",
        summary="用户本周正在准备周五的答辩，主要任务是修改 PPT。",
        source_memory_ids=(MemoryId("l1-a"), MemoryId("l1-b")),
        generator_name="synthetic",
        generator_version="1",
        generated_at=NOW,
    )
    assert candidate.status == ScenarioStatus.CANDIDATE
    assert len(l2_store.list_sources(candidate.id)) == 2

    accepted = service.review(
        candidate.id,
        ScenarioReviewDecision.ACCEPTED,
        expected_revision=1,
        reviewed_at=NOW,
    )
    assert accepted.status == ScenarioStatus.ACTIVE
    assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 2
    connection.close()
