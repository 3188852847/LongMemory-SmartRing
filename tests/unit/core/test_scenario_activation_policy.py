"""L2 自动处置必须由可解释的纯规则决定。"""

from longmemory.core.memory.l2_scenario.activation_policy import (
    ScenarioActivationAction,
    ScenarioActivationReason,
    ScenarioEvidenceSummary,
    ScenarioRiskAssessment,
    decide_scenario_activation,
)


def test_three_memories_and_messages_can_auto_activate():
    decision = decide_scenario_activation(
        evidence=ScenarioEvidenceSummary(3, 3), risk=ScenarioRiskAssessment(),
    )
    assert (decision.action, decision.reason) == (
        ScenarioActivationAction.AUTO_ACTIVATE,
        ScenarioActivationReason.STRONG_EVIDENCE,
    )


def test_minimum_candidate_evidence_is_held_for_more_observations():
    decision = decide_scenario_activation(
        evidence=ScenarioEvidenceSummary(2, 2), risk=ScenarioRiskAssessment(),
    )
    assert (decision.action, decision.reason) == (
        ScenarioActivationAction.HOLD,
        ScenarioActivationReason.EVIDENCE_INSUFFICIENT,
    )


def test_sensitive_and_ambiguous_sources_are_blocked():
    sensitive = decide_scenario_activation(
        evidence=ScenarioEvidenceSummary(4, 4),
        risk=ScenarioRiskAssessment(sensitive=True),
    )
    ambiguous = decide_scenario_activation(
        evidence=ScenarioEvidenceSummary(4, 4),
        risk=ScenarioRiskAssessment(source_role_ambiguous=True),
    )
    assert sensitive.reason == ScenarioActivationReason.SENSITIVE_CONTENT
    assert ambiguous.reason == ScenarioActivationReason.SOURCE_ROLE_AMBIGUOUS
    assert sensitive.action == ambiguous.action == ScenarioActivationAction.BLOCK


def test_unresolved_conflict_is_held_not_silently_accepted():
    decision = decide_scenario_activation(
        evidence=ScenarioEvidenceSummary(4, 4),
        risk=ScenarioRiskAssessment(unresolved_conflict=True),
    )
    assert (decision.action, decision.reason) == (
        ScenarioActivationAction.HOLD,
        ScenarioActivationReason.UNRESOLVED_CONFLICT,
    )
