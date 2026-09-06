"""两阶段真实周期只使用独立连接，并按顺序留下各自账本结果。"""

from datetime import UTC, datetime, timedelta

import pytest

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.consolidation.cycle import LowFrequencyConsolidationCycle
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    CURRENT_USER_SUBJECT_ID,
    MemoryEvidence,
    MemorySourceType,
)
from longmemory.core.memory.consolidation.risk_review import ConsolidationRiskReview
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


class ScenarioProducer:
    def propose(self, *, sources):
        ids = [str(item.memory_id) for item in sources[:3]]
        return (
            '{"schema_version":2,"candidate":{"title":"饮品偏好",'
            '"summary":"用户近期在选择茶饮。","source_memory_ids":'
            + str(ids).replace("'", '"') + "}}"
        )


class PersonaProducer:
    def propose_consolidation(self, **_kwargs):
        raise AssertionError("单个新 L2 不满足 L3 门槛，不应调用画像模型")


class RiskReviewer:
    ready = True
    version = "risk-review-test"

    def review(self, _value):
        return ConsolidationRiskReview(
            assessment_complete=True,
            sensitive=False,
            unresolved_conflict=False,
            clarification_allowed=False,
            reason_codes=("low_risk",),
            reviewer_version=self.version,
        )


def test_cycle_runs_l1_then_rechecks_l2_with_a_separate_connection(tmp_path):
    database = tmp_path / "cycle.db"
    connection = open_database(database)
    initialize_schema(connection)
    messages = SQLiteConversationStore(connection)
    memories = SQLiteMemoryStore(connection)
    base = datetime.now(UTC) - timedelta(days=1)
    for index in range(4):
        message_id = MessageId(f"l0-{index}")
        memory_id = MemoryId(f"l1-{index}")
        moment = base + timedelta(minutes=index)
        messages.save(ConversationMessage(message_id, MessageRole.USER, f"饮品记录 {index}", moment))
        memories.save(
            AtomicMemory(memory_id, CURRENT_USER_SUBJECT_ID, f"用户饮品记录 {index}。", moment),
            MemoryEvidence(memory_id, message_id, MemorySourceType.USER_STATED, moment),
        )
    connection.close()
    outcome = LowFrequencyConsolidationCycle(
        database=database,
        scenario_producer=ScenarioProducer(),
        persona_producer=PersonaProducer(),
        risk_reviewer=RiskReviewer(),
        generator_name="synthetic",
        scenario_generator_version="scenario-test",
        persona_generator_version="persona-test",
    )("user:self")

    connection = open_database(database)
    runs = connection.execute(
        "SELECT stage,status,outcome_code,risk_reviewer_version "
        "FROM memory_consolidation_runs ORDER BY started_at,id"
    ).fetchall()
    assert [tuple(row) for row in runs] == [
        ("l1_to_l2", "completed", "scenario_activated", "risk-review-test"),
    ]
    assert "l1_to_l2:completed:scenario_activated" in outcome
    assert "l2_to_l3:hold:below_source_threshold" in outcome
    connection.close()


def test_cycle_refuses_missing_database_without_creating_it(tmp_path):
    database = tmp_path / "missing.db"
    cycle = LowFrequencyConsolidationCycle(
        database=database,
        scenario_producer=ScenarioProducer(),
        persona_producer=PersonaProducer(),
        risk_reviewer=RiskReviewer(),
        generator_name="synthetic",
        scenario_generator_version="scenario-test",
        persona_generator_version="persona-test",
    )

    with pytest.raises(RuntimeError, match="consolidation_database_missing"):
        cycle("user:self")
    assert database.exists() is False
