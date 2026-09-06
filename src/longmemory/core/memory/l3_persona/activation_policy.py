"""L3 候选的确定性自动处置策略。

本模块只回答“候选下一步应该去哪里”，不调用模型、不访问数据库，也不执行接受。
调用方必须从受信任的规则或配置提供风险标记，不能采用模型自报的安全等级。
"""

from dataclasses import dataclass
from enum import StrEnum

from .consolidation import PersonaConsolidationOperation, PersonaConsolidationSuggestion
from .models import PersonaBasis


class PersonaActivationAction(StrEnum):
    """产品路径允许的四种候选处置，不包含删除。"""

    AUTO_ACTIVATE = "auto_activate"
    HOLD = "hold"
    ASK_NATURALLY = "ask_naturally"
    BLOCK = "block"


class PersonaActivationReason(StrEnum):
    """稳定原因码用于测试、审计与未来控制台解释。"""

    NO_CANDIDATE = "no_candidate"
    SENSITIVE_CONTENT = "sensitive_content"
    SOURCE_ROLE_AMBIGUOUS = "source_role_ambiguous"
    UPDATE_TARGET_NOT_CURRENT = "update_target_not_current"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    DECLARED_LOW_RISK = "declared_low_risk"
    DECLARED_EVIDENCE_INSUFFICIENT = "declared_evidence_insufficient"
    INFERENCE_EVIDENCE_INSUFFICIENT = "inference_evidence_insufficient"
    INFERENCE_STRONG_EVIDENCE = "inference_strong_evidence"


@dataclass(frozen=True, slots=True)
class PersonaEvidenceSummary:
    """只保存门控需要的计数，不复制个人记忆正文。"""

    source_count: int
    user_message_count: int
    observation_day_count: int

    def __post_init__(self) -> None:
        if min(self.source_count, self.user_message_count, self.observation_day_count) < 0:
            raise ValueError("persona_activation_evidence_invalid")


@dataclass(frozen=True, slots=True)
class PersonaRiskAssessment:
    """由模型之外的受信任边界提供的风险事实。"""

    sensitive: bool = False
    source_role_ambiguous: bool = False
    unresolved_conflict: bool = False
    clarification_allowed: bool = True
    update_target_is_current: bool = True


@dataclass(frozen=True, slots=True)
class PersonaActivationDecision:
    action: PersonaActivationAction
    reason: PersonaActivationReason
    policy_version: str = "persona-activation-v1"


def decide_persona_activation(
    suggestion: PersonaConsolidationSuggestion,
    *,
    evidence: PersonaEvidenceSummary,
    risk: PersonaRiskAssessment,
) -> PersonaActivationDecision:
    """在任何持久化之前，确定 L3 整理建议的下一步。

    现有 L3 推断最低门槛是 2 个来源、3 条用户原话、2 个观察日；自动激活
    采用更强的 3/5/3 门槛。最低门槛与自动门槛之间的候选进入 HOLD，继续
    累积证据，而不是为了减少网页确认就降低画像可信度。
    """

    if suggestion.operation == PersonaConsolidationOperation.NOOP:
        return PersonaActivationDecision(
            PersonaActivationAction.HOLD,
            PersonaActivationReason.NO_CANDIDATE,
        )
    if suggestion.candidate is None:
        raise ValueError("persona_activation_candidate_required")

    # 风险规则优先于便利性；即使证据很多也不能覆盖敏感或错误归因。
    if risk.sensitive:
        return PersonaActivationDecision(
            PersonaActivationAction.BLOCK,
            PersonaActivationReason.SENSITIVE_CONTENT,
        )
    if risk.source_role_ambiguous:
        return PersonaActivationDecision(
            PersonaActivationAction.BLOCK,
            PersonaActivationReason.SOURCE_ROLE_AMBIGUOUS,
        )
    if (
        suggestion.operation == PersonaConsolidationOperation.UPDATE
        and not risk.update_target_is_current
    ):
        return PersonaActivationDecision(
            PersonaActivationAction.BLOCK,
            PersonaActivationReason.UPDATE_TARGET_NOT_CURRENT,
        )
    if risk.unresolved_conflict:
        if risk.clarification_allowed:
            return PersonaActivationDecision(
                PersonaActivationAction.ASK_NATURALLY,
                PersonaActivationReason.CLARIFICATION_REQUIRED,
            )
        return PersonaActivationDecision(
            PersonaActivationAction.HOLD,
            PersonaActivationReason.UNRESOLVED_CONFLICT,
        )

    if suggestion.candidate.basis == PersonaBasis.USER_DECLARED:
        if min(
            evidence.source_count,
            evidence.user_message_count,
            evidence.observation_day_count,
        ) < 1:
            return PersonaActivationDecision(
                PersonaActivationAction.HOLD,
                PersonaActivationReason.DECLARED_EVIDENCE_INSUFFICIENT,
            )
        return PersonaActivationDecision(
            PersonaActivationAction.AUTO_ACTIVATE,
            PersonaActivationReason.DECLARED_LOW_RISK,
        )

    if (
        evidence.source_count >= 3
        and evidence.user_message_count >= 5
        and evidence.observation_day_count >= 3
    ):
        return PersonaActivationDecision(
            PersonaActivationAction.AUTO_ACTIVATE,
            PersonaActivationReason.INFERENCE_STRONG_EVIDENCE,
        )
    return PersonaActivationDecision(
        PersonaActivationAction.HOLD,
        PersonaActivationReason.INFERENCE_EVIDENCE_INSUFFICIENT,
    )
