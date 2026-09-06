"""把 L3 确定性门控接到既有候选与复核事务，不负责触发模型。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.memory.l3_persona.activation_policy import (
    PersonaActivationAction,
    PersonaActivationDecision,
    PersonaEvidenceSummary,
    PersonaRiskAssessment,
    decide_persona_activation,
)
from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationOperation,
    PersonaConsolidationSuggestion,
)
from longmemory.core.memory.l3_persona.contracts import PersonaStore
from longmemory.core.memory.l3_persona.models import (
    PersonaMemory,
    PersonaReviewDecision,
    PersonaReviewerType,
)

from .service import PersonaManagementService


@dataclass(frozen=True, slots=True)
class PersonaActivationResult:
    """一次受控处置的结果；persona 为空表示没有产生持久画像。"""

    decision: PersonaActivationDecision
    persona: PersonaMemory | None


class PersonaActivationService:
    """只执行已经通过规则门控的低风险 L3 建议。

    调用方应为存储提供一个外层事务，并只在本方法成功返回后提交。SQLite
    入口使用 ``commit_changes=False``，因此候选创建、策略复核和可能发生的
    旧画像失效会一起提交或一起回滚。
    """

    def __init__(self, *, persona_store: PersonaStore) -> None:
        self._store = persona_store
        self._management = PersonaManagementService(persona_store=persona_store)

    def apply(
        self,
        suggestion: PersonaConsolidationSuggestion,
        *,
        risk: PersonaRiskAssessment,
        generator_name: str,
        generator_version: str,
        generated_at: datetime | None = None,
    ) -> PersonaActivationResult:
        """重新读取证据并执行决定，非自动通过结果绝不落成 active。"""

        candidate = suggestion.candidate
        if (
            suggestion.operation == PersonaConsolidationOperation.NOOP
            and (candidate is not None or suggestion.replaces)
        ):
            raise ValueError("persona_activation_operation_invalid")
        if (
            suggestion.operation == PersonaConsolidationOperation.ADD
            and (candidate is None or suggestion.replaces)
        ):
            raise ValueError("persona_activation_operation_invalid")
        if (
            suggestion.operation == PersonaConsolidationOperation.UPDATE
            and (candidate is None or len(suggestion.replaces) != 1)
        ):
            raise ValueError("persona_activation_operation_invalid")
        if candidate is None:
            evidence = PersonaEvidenceSummary(0, 0, 0)
        else:
            if not candidate.source_refs or len(set(candidate.source_refs)) != len(
                candidate.source_refs
            ):
                raise ValueError("persona_activation_sources_invalid")
            resolved = tuple(
                self._store.resolve_source(layer, source_id)
                for layer, source_id in candidate.source_refs
            )
            if any(source is None for source in resolved):
                raise ValueError("persona_source_missing_or_inactive")
            resolved_sources = tuple(source for source in resolved if source is not None)
            messages = {
                message_id
                for source in resolved_sources
                for message_id in source.user_message_ids
            }
            days = {
                day
                for source in resolved_sources
                for day in source.observation_days
            }
            evidence = PersonaEvidenceSummary(
                len(resolved_sources), len(messages), len(days),
            )

        decision = decide_persona_activation(
            suggestion,
            evidence=evidence,
            risk=risk,
        )
        if decision.action != PersonaActivationAction.AUTO_ACTIVATE:
            return PersonaActivationResult(decision, None)
        if candidate is None:  # 决策器契约已保证；保留防御以免未来策略回归。
            raise RuntimeError("persona_activation_candidate_missing")

        persona = self._management.create_candidate(
            kind=candidate.kind,
            basis=candidate.basis,
            label=candidate.label,
            statement=candidate.statement,
            source_refs=candidate.source_refs,
            generator_name=generator_name,
            generator_version=generator_version,
            generated_at=generated_at,
            replaces=suggestion.replaces,
        )
        persona = self._management.review(
            persona.id,
            PersonaReviewDecision.ACCEPTED,
            expected_revision=persona.revision,
            reviewed_at=generated_at,
            reviewer_type=PersonaReviewerType.POLICY,
            policy_version=decision.policy_version,
            decision_reason=decision.reason.value,
        )
        return PersonaActivationResult(decision, persona)
