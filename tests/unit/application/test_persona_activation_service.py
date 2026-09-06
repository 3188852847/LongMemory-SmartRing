"""P3.6 只让确定性策略接受低风险画像，其他处置不得落成 active。"""

from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.application.persona_management.activation_service import (
    PersonaActivationService,
)
from longmemory.core.common.identifiers import PersonaId
from longmemory.core.memory.l3_persona.activation_policy import (
    PersonaActivationAction,
    PersonaRiskAssessment,
)
from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationOperation,
    PersonaConsolidationSuggestion,
)
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaReviewDecision,
    PersonaReviewerType,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import PersonaProposal
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


def prepared(tmp_path):
    connection = open_database(tmp_path / "activation.db")
    initialize_schema(connection)
    rows = [
        ("l0-a", "我喜欢喝乌龙茶。", "2026-09-04T05:00:00+00:00", "l1-a", "用户喜欢喝乌龙茶。"),
        ("l0-b", "这周我又喝了乌龙茶。", "2026-09-05T05:00:00+00:00", "l1-b", "用户这周喝了乌龙茶。"),
        ("l0-c", "今天下午也喝了乌龙茶。", "2026-09-06T05:00:00+00:00", "l1-c", "用户今天下午喝了乌龙茶。"),
    ]
    for message_id, text, created_at, memory_id, content in rows:
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?, 'user', ?, ?)",
            (message_id, text, created_at),
        )
        connection.execute(
            "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
            "VALUES (?,'user:self',?,?)",
            (memory_id, content, created_at),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?, 'user_stated', ?)",
            (memory_id, message_id, created_at),
        )
    connection.commit()
    return connection


def suggestion(*, basis=PersonaBasis.USER_DECLARED, operation=PersonaConsolidationOperation.ADD,
               sources=((PersonaSourceLayer.L1, "l1-a"),), replaces=()):
    proposal = PersonaProposal(
        PersonaKind.PREFERENCE,
        basis,
        "饮品偏好",
        "用户明确表示喜欢喝乌龙茶。",
        sources,
    )
    return PersonaConsolidationSuggestion(operation, proposal, replaces)


def test_declared_low_risk_is_activated_with_policy_audit(tmp_path):
    connection = prepared(tmp_path)
    store = SQLitePersonaStore(connection, commit_changes=False)
    result = PersonaActivationService(persona_store=store).apply(
        suggestion(),
        risk=PersonaRiskAssessment(assessment_complete=True),
        generator_name="model_consolidation_runtime",
        generator_version="l3-persona-consolidation-v1",
        generated_at=datetime(2026, 9, 6, 20, 0, tzinfo=UTC),
    )
    connection.commit()

    assert result.decision.action == PersonaActivationAction.AUTO_ACTIVATE
    assert result.persona is not None and result.persona.status.value == "active"
    review = store.get_review(result.persona.id)
    assert review is not None
    assert review.decision == PersonaReviewDecision.ACCEPTED
    assert review.reviewer_type == PersonaReviewerType.POLICY
    assert review.policy_version == "persona-activation-v1"
    assert review.decision_reason == "declared_low_risk"
    connection.close()


def test_sensitive_or_insufficient_suggestion_never_persists(tmp_path):
    connection = prepared(tmp_path)
    service = PersonaActivationService(
        persona_store=SQLitePersonaStore(connection, commit_changes=False),
    )
    blocked = service.apply(
        suggestion(),
        risk=PersonaRiskAssessment(assessment_complete=True, sensitive=True),
        generator_name="synthetic",
        generator_version="1",
    )
    held = service.apply(
        suggestion(
            basis=PersonaBasis.SYSTEM_INFERRED,
            sources=((PersonaSourceLayer.L1, "l1-a"), (PersonaSourceLayer.L1, "l1-b")),
        ),
        risk=PersonaRiskAssessment(assessment_complete=True),
        generator_name="synthetic",
        generator_version="1",
    )

    assert blocked.decision.action == PersonaActivationAction.BLOCK
    assert held.decision.action == PersonaActivationAction.HOLD
    assert blocked.persona is None and held.persona is None
    assert connection.execute("SELECT COUNT(*) FROM persona_memories").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM persona_reviews").fetchone()[0] == 0
    connection.close()


def test_executor_rejects_operation_payload_mismatch_before_writing(tmp_path):
    connection = prepared(tmp_path)
    service = PersonaActivationService(
        persona_store=SQLitePersonaStore(connection, commit_changes=False),
    )
    malformed = PersonaConsolidationSuggestion(
        PersonaConsolidationOperation.ADD,
        suggestion().candidate,
        (PersonaId("unexpected-replacement"),),
    )

    with pytest.raises(ValueError, match="persona_activation_operation_invalid"):
        service.apply(
            malformed,
            risk=PersonaRiskAssessment(assessment_complete=True),
            generator_name="synthetic",
            generator_version="1",
        )

    assert connection.execute("SELECT COUNT(*) FROM persona_memories").fetchone()[0] == 0
    connection.close()


def test_automatic_update_uses_existing_atomic_replacement_path(tmp_path):
    connection = prepared(tmp_path)
    store = SQLitePersonaStore(connection, commit_changes=False)
    activator = PersonaActivationService(persona_store=store)
    old = activator.apply(
        suggestion(),
        risk=PersonaRiskAssessment(assessment_complete=True),
        generator_name="synthetic",
        generator_version="1",
    ).persona
    assert old is not None
    connection.commit()

    update = suggestion(
        operation=PersonaConsolidationOperation.UPDATE,
        sources=((PersonaSourceLayer.L1, "l1-b"),),
        replaces=(PersonaId(str(old.id)),),
    )
    current = activator.apply(
        update,
        risk=PersonaRiskAssessment(
            assessment_complete=True, update_target_is_current=True,
        ),
        generator_name="synthetic",
        generator_version="2",
    ).persona
    connection.commit()

    assert current is not None and current.status.value == "active"
    assert store.get(old.id).status.value == "stale"
    assert store.list_replacements(current.id)[0].applied_at is not None
    assert store.get_review(current.id).reviewer_type == PersonaReviewerType.POLICY
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
