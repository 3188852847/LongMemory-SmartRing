"""圆屏产品的 L3 自动处置先以纯策略验证，不触碰数据库。"""

from longmemory.core.memory.l3_persona.activation_policy import (
    PersonaActivationAction,
    PersonaActivationReason,
    PersonaEvidenceSummary,
    PersonaRiskAssessment,
    decide_persona_activation,
)
from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationOperation,
    PersonaConsolidationSuggestion,
)
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import PersonaProposal


def suggestion(
    *,
    basis: PersonaBasis = PersonaBasis.USER_DECLARED,
    operation: PersonaConsolidationOperation = PersonaConsolidationOperation.ADD,
) -> PersonaConsolidationSuggestion:
    if operation == PersonaConsolidationOperation.NOOP:
        return PersonaConsolidationSuggestion(operation, None, ())
    candidate = PersonaProposal(
        kind=PersonaKind.PREFERENCE,
        basis=basis,
        label="饮品偏好",
        statement="用户喜欢清淡乌龙茶。",
        source_refs=((PersonaSourceLayer.L1, "l1-tea"),),
    )
    replaces = () if operation == PersonaConsolidationOperation.ADD else ("old",)
    return PersonaConsolidationSuggestion(operation, candidate, replaces)


def evidence(source_count=1, user_message_count=1, observation_day_count=1):
    return PersonaEvidenceSummary(source_count, user_message_count, observation_day_count)


def test_noop_never_creates_an_activation():
    decision = decide_persona_activation(
        suggestion(operation=PersonaConsolidationOperation.NOOP),
        evidence=evidence(0, 0, 0),
        risk=PersonaRiskAssessment(),
    )
    assert decision.action == PersonaActivationAction.HOLD
    assert decision.reason == PersonaActivationReason.NO_CANDIDATE


def test_explicit_low_risk_statement_can_activate_without_web_review():
    decision = decide_persona_activation(
        suggestion(), evidence=evidence(), risk=PersonaRiskAssessment(),
    )
    assert decision.action == PersonaActivationAction.AUTO_ACTIVATE
    assert decision.reason == PersonaActivationReason.DECLARED_LOW_RISK


def test_explicit_statement_without_a_user_source_is_held():
    decision = decide_persona_activation(
        suggestion(), evidence=evidence(1, 0, 1), risk=PersonaRiskAssessment(),
    )
    assert decision.action == PersonaActivationAction.HOLD
    assert decision.reason == PersonaActivationReason.DECLARED_EVIDENCE_INSUFFICIENT


def test_minimum_inference_evidence_is_not_enough_for_automatic_activation():
    decision = decide_persona_activation(
        suggestion(basis=PersonaBasis.SYSTEM_INFERRED),
        evidence=evidence(2, 3, 2),
        risk=PersonaRiskAssessment(),
    )
    assert decision.action == PersonaActivationAction.HOLD
    assert decision.reason == PersonaActivationReason.INFERENCE_EVIDENCE_INSUFFICIENT


def test_strong_cross_observation_inference_can_activate():
    decision = decide_persona_activation(
        suggestion(basis=PersonaBasis.SYSTEM_INFERRED),
        evidence=evidence(3, 5, 3),
        risk=PersonaRiskAssessment(),
    )
    assert decision.action == PersonaActivationAction.AUTO_ACTIVATE
    assert decision.reason == PersonaActivationReason.INFERENCE_STRONG_EVIDENCE


def test_sensitive_or_ambiguous_source_is_blocked_before_convenience_rules():
    sensitive = decide_persona_activation(
        suggestion(), evidence=evidence(), risk=PersonaRiskAssessment(sensitive=True),
    )
    ambiguous = decide_persona_activation(
        suggestion(),
        evidence=evidence(),
        risk=PersonaRiskAssessment(source_role_ambiguous=True),
    )
    assert (sensitive.action, sensitive.reason) == (
        PersonaActivationAction.BLOCK, PersonaActivationReason.SENSITIVE_CONTENT,
    )
    assert (ambiguous.action, ambiguous.reason) == (
        PersonaActivationAction.BLOCK, PersonaActivationReason.SOURCE_ROLE_AMBIGUOUS,
    )


def test_conflict_uses_natural_clarification_when_allowed_otherwise_holds():
    ask = decide_persona_activation(
        suggestion(),
        evidence=evidence(),
        risk=PersonaRiskAssessment(unresolved_conflict=True),
    )
    hold = decide_persona_activation(
        suggestion(),
        evidence=evidence(),
        risk=PersonaRiskAssessment(
            unresolved_conflict=True, clarification_allowed=False,
        ),
    )
    assert ask.action == PersonaActivationAction.ASK_NATURALLY
    assert ask.reason == PersonaActivationReason.CLARIFICATION_REQUIRED
    assert hold.action == PersonaActivationAction.HOLD
    assert hold.reason == PersonaActivationReason.UNRESOLVED_CONFLICT


def test_update_with_stale_target_is_blocked_for_revision_recheck():
    decision = decide_persona_activation(
        suggestion(operation=PersonaConsolidationOperation.UPDATE),
        evidence=evidence(),
        risk=PersonaRiskAssessment(update_target_is_current=False),
    )
    assert decision.action == PersonaActivationAction.BLOCK
    assert decision.reason == PersonaActivationReason.UPDATE_TARGET_NOT_CURRENT


def test_evidence_counts_cannot_be_negative():
    try:
        evidence(-1, 0, 0)
    except ValueError as error:
        assert str(error) == "persona_activation_evidence_invalid"
    else:
        raise AssertionError("negative evidence must fail")
