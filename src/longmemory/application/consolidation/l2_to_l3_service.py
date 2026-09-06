"""按持久预算执行一次 L2→L3 整理；尚不负责后台触发。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from longmemory.application.persona_management.activation_service import (
    PersonaActivationService,
)
from longmemory.application.persona_management.consolidation_service import (
    PersonaConsolidationService,
)
from longmemory.core.memory.consolidation.contracts import (
    ConsolidationRunStore,
    L2ConsolidationSourceReader,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.risk_review import (
    ConsolidationRiskEvidence,
    ConsolidationRiskReview,
    ConsolidationRiskReviewError,
    ConsolidationRiskReviewInput,
    ConsolidationRiskReviewer,
)
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerAction,
    ConsolidationTriggerConfig,
    ConsolidationTriggerDecision,
    ConsolidationTriggerReason,
)
from longmemory.core.memory.l3_persona.activation_policy import (
    PersonaActivationDecision,
    PersonaRiskAssessment,
)
from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationOperation,
    PersonaConsolidationProducer,
)
from longmemory.core.memory.l3_persona.contracts import PersonaStore
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaMemory,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)

from .run_coordinator import ConsolidationRunCoordinator


L3_TRIGGER_CONFIG = ConsolidationTriggerConfig(
    minimum_new_sources=2,
    maximum_sources_per_run=12,
    cooldown=timedelta(hours=24),
    daily_model_call_budget=2,
    model_calls_per_run=2,
)


@dataclass(frozen=True, slots=True)
class L2ToL3ConsolidationResult:
    trigger_decision: ConsolidationTriggerDecision
    run: ConsolidationRun | None
    activation_decision: PersonaActivationDecision | None = None
    persona: PersonaMemory | None = None
    risk_review: ConsolidationRiskReview | None = None


class L2ToL3ConsolidationService:
    def __init__(
        self,
        *,
        run_store: ConsolidationRunStore,
        source_reader: L2ConsolidationSourceReader,
        consolidation_producer: PersonaConsolidationProducer,
        risk_reviewer: ConsolidationRiskReviewer,
        persona_store: PersonaStore,
        config: ConsolidationTriggerConfig = L3_TRIGGER_CONFIG,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._run_store = run_store
        self._source_reader = source_reader
        self._consolidation = PersonaConsolidationService(consolidation_producer)
        self._risk_reviewer = risk_reviewer
        self._activation = PersonaActivationService(persona_store=persona_store)
        self._persona_store = persona_store
        self._config = config
        self._clock = clock

    def run_once(
        self,
        *,
        subject_id: str,
        trigger: ConsolidationTrigger,
        budget_window_start: datetime,
        generator_name: str,
        generator_version: str,
    ) -> L2ToL3ConsolidationResult:
        if not self._risk_reviewer.ready:
            return L2ToL3ConsolidationResult(
                ConsolidationTriggerDecision(
                    ConsolidationTriggerAction.HOLD,
                    ConsolidationTriggerReason.RISK_ASSESSMENT_INCOMPLETE,
                ),
                None,
            )
        started_at = self._clock()
        batch = self._source_reader.read_batch(
            subject_id,
            after=self._run_store.latest_cursor(
                subject_id, ConsolidationStage.L2_TO_L3,
            ),
            limit=self._config.maximum_sources_per_run,
            now=started_at,
        )
        start = ConsolidationRunCoordinator(
            self._run_store, config=self._config,
        ).try_start(
            subject_id=subject_id,
            stage=ConsolidationStage.L2_TO_L3,
            trigger=trigger,
            pending_source_count=batch.pending_new_source_count,
            selected_source_count=len(batch.sources) or None,
            now=started_at,
            budget_window_start=budget_window_start,
        )
        if start.run is None:
            return L2ToL3ConsolidationResult(start.decision, None)

        running = start.run
        inputs = tuple(PersonaProposalInput(
            PersonaSourceLayer.L2,
            str(item.scenario_id),
            item.subject_id,
            item.content,
            tuple(PersonaProposalEvidence(
                evidence.message_id, evidence.content, evidence.observation_day,
            ) for evidence in item.evidence),
        ) for item in batch.sources)
        active = self._persona_store.list_active(inputs[0].subject_id)
        try:
            suggestion = self._consolidation.preview(
                basis=PersonaBasis.SYSTEM_INFERRED,
                sources=inputs,
                active_personas=active,
            )
        except PersonaProposalError as error:
            code = str(error)
            no_model = code in {
                "persona_inference_evidence_threshold_not_met",
                "persona_sources_invalid",
            }
            terminal = self._terminal(
                running,
                ConsolidationRunStatus.COMPLETED if no_model else ConsolidationRunStatus.FAILED,
                "evidence_insufficient" if no_model else code or "persona_consolidation_failed",
                batch.next_cursor if no_model else None,
                model_calls=0 if no_model else 1,
            )
            self._run_store.finish(terminal)
            return L2ToL3ConsolidationResult(start.decision, terminal)

        if suggestion.operation == PersonaConsolidationOperation.NOOP:
            terminal = self._terminal(
                running, ConsolidationRunStatus.COMPLETED,
                "persona_noop", batch.next_cursor, model_calls=1,
            )
            self._run_store.finish(terminal)
            return L2ToL3ConsolidationResult(start.decision, terminal)

        candidate = suggestion.candidate
        if candidate is None:
            raise RuntimeError("persona_consolidation_candidate_missing")
        selected = {
            (item.source_layer, item.source_id): item for item in inputs
            if (item.source_layer, item.source_id) in candidate.source_refs
        }
        try:
            review = self._risk_reviewer.review(ConsolidationRiskReviewInput(
                stage=ConsolidationStage.L2_TO_L3,
                operation=suggestion.operation.value,
                candidate=(
                    f"{candidate.kind.value}/{candidate.basis.value}/"
                    f"{candidate.label}：{candidate.statement}"
                ),
                evidence=tuple(
                    ConsolidationRiskEvidence(
                        f"{layer.value}:{source_id}", selected[(layer, source_id)].content,
                    )
                    for layer, source_id in candidate.source_refs
                ),
                current_memories=tuple(
                    ConsolidationRiskEvidence(str(item.id), item.statement)
                    for item in active
                ),
            ))
        except (ConsolidationRiskReviewError, ValueError):
            terminal = self._terminal(
                running, ConsolidationRunStatus.FAILED,
                "risk_review_failed", None, model_calls=2,
            )
            self._run_store.finish(terminal)
            return L2ToL3ConsolidationResult(start.decision, terminal)

        risk = PersonaRiskAssessment(
            assessment_complete=review.assessment_complete,
            sensitive=review.sensitive,
            source_role_ambiguous=False,
            unresolved_conflict=review.unresolved_conflict,
            clarification_allowed=review.clarification_allowed,
            update_target_is_current=True,
        )
        try:
            activated = self._activation.apply(
                suggestion,
                risk=risk,
                generator_name=generator_name,
                generator_version=f"{generator_version}+{review.reviewer_version}",
                generated_at=started_at,
            )
            terminal = self._terminal(
                running,
                ConsolidationRunStatus.COMPLETED,
                (
                    "persona_activated"
                    if activated.persona is not None
                    else "persona_" + activated.decision.reason.value
                ),
                batch.next_cursor,
                model_calls=2,
            )
            self._run_store.finish(terminal)
        except Exception:
            terminal = self._terminal(
                running, ConsolidationRunStatus.FAILED,
                "persona_activation_failed", None, model_calls=2,
            )
            self._run_store.finish(terminal)
            return L2ToL3ConsolidationResult(start.decision, terminal)
        return L2ToL3ConsolidationResult(
            start.decision, terminal, activated.decision, activated.persona, review,
        )

    def _terminal(self, running, status, outcome, cursor, *, model_calls):
        return ConsolidationRun(
            running.id, running.subject_id, running.stage, running.trigger,
            status, running.started_at, running.source_count, model_calls,
            self._clock(), outcome, cursor,
        )
