"""L2 自动生效复用候选与复核事务，并明确记录 policy 身份。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.application.scenario_management.activation_service import (
    ScenarioActivationService,
)
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l2_scenario.activation_policy import (
    ScenarioActivationAction,
    ScenarioRiskAssessment,
)
from longmemory.core.memory.l2_scenario.models import ScenarioReviewerType
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposal,
    ScenarioProposalInput,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 20, 0, tzinfo=UTC)


def prepared(tmp_path):
    connection = open_database(tmp_path / "l2-activation.db")
    initialize_schema(connection)
    inputs = []
    for number in range(1, 5):
        moment = NOW - timedelta(days=4 - number)
        memory_id, message_id = f"l1-{number}", f"l0-{number}"
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,'user',?,?)",
            (message_id, f"答辩准备原话 {number}", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
            "VALUES (?,'user:self',?,?)",
            (memory_id, f"用户正在准备答辩 {number}。", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
            (memory_id, message_id, moment.isoformat()),
        )
        inputs.append(ScenarioProposalInput(
            MemoryId(memory_id), MemorySubjectId("user:self"),
            f"用户正在准备答辩 {number}。", (message_id,),
        ))
    connection.commit()
    return connection, tuple(inputs)


def test_strong_low_risk_scenario_is_activated_with_policy_audit(tmp_path):
    connection, inputs = prepared(tmp_path)
    memory_store = SQLiteMemoryStore(connection, commit_changes=False)
    scenario_store = SQLiteScenarioStore(connection, commit_changes=False)
    result = ScenarioActivationService(
        memory_store=memory_store, scenario_store=scenario_store,
    ).apply(
        ScenarioProposal(
            "准备毕业答辩", "用户最近在持续准备毕业答辩。",
            tuple(item.memory_id for item in inputs[:3]),
        ),
        inputs=inputs,
        risk=ScenarioRiskAssessment(assessment_complete=True),
        generator_name="model_consolidation_runtime",
        generator_version="l2-scenario-preview-v2",
        generated_at=NOW,
    )
    connection.commit()

    assert result.decision.action == ScenarioActivationAction.AUTO_ACTIVATE
    assert result.scenario is not None and result.scenario.status.value == "active"
    review = scenario_store.get_review(result.scenario.id)
    assert review is not None and review.reviewer_type == ScenarioReviewerType.POLICY
    assert review.policy_version == "scenario-activation-v1"
    assert review.decision_reason == "strong_evidence"
    connection.close()


def test_insufficient_or_sensitive_proposal_does_not_persist(tmp_path):
    connection, inputs = prepared(tmp_path)
    service = ScenarioActivationService(
        memory_store=SQLiteMemoryStore(connection, commit_changes=False),
        scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
    )
    held = service.apply(
        ScenarioProposal(
            "准备答辩", "用户在准备答辩。",
            tuple(item.memory_id for item in inputs[:2]),
        ),
        inputs=inputs,
        risk=ScenarioRiskAssessment(assessment_complete=True),
        generator_name="synthetic", generator_version="1",
    )
    blocked = service.apply(
        ScenarioProposal(
            "敏感场景", "不应自动落库。",
            tuple(item.memory_id for item in inputs[:3]),
        ),
        inputs=inputs,
        risk=ScenarioRiskAssessment(assessment_complete=True, sensitive=True),
        generator_name="synthetic", generator_version="1",
    )
    assert held.decision.action == ScenarioActivationAction.HOLD
    assert blocked.decision.action == ScenarioActivationAction.BLOCK
    assert held.scenario is None and blocked.scenario is None
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM scenario_reviews").fetchone()[0] == 0
    connection.close()
