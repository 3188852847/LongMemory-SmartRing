"""L2 场景候选的确定性自动生效门控；模型不能自报安全。"""

from dataclasses import dataclass
from enum import StrEnum


class ScenarioActivationAction(StrEnum):
    AUTO_ACTIVATE = "auto_activate"
    HOLD = "hold"
    BLOCK = "block"


class ScenarioActivationReason(StrEnum):
    STRONG_EVIDENCE = "strong_evidence"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    SENSITIVE_CONTENT = "sensitive_content"
    SOURCE_ROLE_AMBIGUOUS = "source_role_ambiguous"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    RISK_ASSESSMENT_INCOMPLETE = "risk_assessment_incomplete"


@dataclass(frozen=True, slots=True)
class ScenarioEvidenceSummary:
    source_memory_count: int
    user_message_count: int

    def __post_init__(self) -> None:
        if min(self.source_memory_count, self.user_message_count) < 0:
            raise ValueError("scenario_activation_evidence_invalid")


@dataclass(frozen=True, slots=True)
class ScenarioRiskAssessment:
    assessment_complete: bool
    sensitive: bool = False
    source_role_ambiguous: bool = False
    unresolved_conflict: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioActivationDecision:
    action: ScenarioActivationAction
    reason: ScenarioActivationReason
    policy_version: str = "scenario-activation-v1"


def decide_scenario_activation(
    *,
    evidence: ScenarioEvidenceSummary,
    risk: ScenarioRiskAssessment,
) -> ScenarioActivationDecision:
    """三条 L1/三条用户原话是首版保守产品门槛，不是质量结论。"""

    if risk.sensitive:
        return ScenarioActivationDecision(
            ScenarioActivationAction.BLOCK,
            ScenarioActivationReason.SENSITIVE_CONTENT,
        )
    if risk.source_role_ambiguous:
        return ScenarioActivationDecision(
            ScenarioActivationAction.BLOCK,
            ScenarioActivationReason.SOURCE_ROLE_AMBIGUOUS,
        )
    if risk.unresolved_conflict:
        return ScenarioActivationDecision(
            ScenarioActivationAction.HOLD,
            ScenarioActivationReason.UNRESOLVED_CONFLICT,
        )
    if not risk.assessment_complete:
        return ScenarioActivationDecision(
            ScenarioActivationAction.HOLD,
            ScenarioActivationReason.RISK_ASSESSMENT_INCOMPLETE,
        )
    if evidence.source_memory_count >= 3 and evidence.user_message_count >= 3:
        return ScenarioActivationDecision(
            ScenarioActivationAction.AUTO_ACTIVATE,
            ScenarioActivationReason.STRONG_EVIDENCE,
        )
    return ScenarioActivationDecision(
        ScenarioActivationAction.HOLD,
        ScenarioActivationReason.EVIDENCE_INSUFFICIENT,
    )
