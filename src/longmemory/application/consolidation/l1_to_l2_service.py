"""按持久预算执行一次 L1→L2 整理；尚不负责何时从聊天路径触发。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from longmemory.application.scenario_management.activation_service import (
    ScenarioActivationService,
)
from longmemory.application.scenario_management.proposal_service import (
    ScenarioProposalService,
)
from longmemory.core.memory.consolidation.contracts import (
    ConsolidationRunStore,
    L1ConsolidationSourceReader,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerAction,
    ConsolidationTriggerConfig,
    ConsolidationTriggerDecision,
)
from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.l2_scenario.activation_policy import (
    ScenarioActivationDecision,
    ScenarioRiskAssessment,
)
from longmemory.core.memory.l2_scenario.contracts import ScenarioStore
from longmemory.core.memory.l2_scenario.models import ScenarioMemory
from longmemory.core.memory.l2_scenario.proposals import (
    ScenarioProposalError,
    ScenarioProposalInput,
    ScenarioProposalProducer,
)

from .run_coordinator import ConsolidationRunCoordinator


@dataclass(frozen=True, slots=True)
class L1ToL2ConsolidationResult:
    trigger_decision: ConsolidationTriggerDecision
    run: ConsolidationRun | None
    activation_decision: ScenarioActivationDecision | None = None
    scenario: ScenarioMemory | None = None


class L1ToL2ConsolidationService:
    """把选择、一次模型建议、门控与账本结束串成可审计事务边界。"""

    def __init__(
        self,
        *,
        run_store: ConsolidationRunStore,
        source_reader: L1ConsolidationSourceReader,
        proposal_producer: ScenarioProposalProducer,
        memory_store: MemoryStore,
        scenario_store: ScenarioStore,
        config: ConsolidationTriggerConfig = ConsolidationTriggerConfig(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._run_store = run_store
        self._source_reader = source_reader
        self._proposal = ScenarioProposalService(proposal_producer)
        self._activation = ScenarioActivationService(
            memory_store=memory_store, scenario_store=scenario_store,
        )
        self._config = config
        self._clock = clock

    def run_once(
        self,
        *,
        subject_id: str,
        trigger: ConsolidationTrigger,
        risk: ScenarioRiskAssessment,
        budget_window_start: datetime,
        generator_name: str,
        generator_version: str,
    ) -> L1ToL2ConsolidationResult:
        """执行一次且不重试；失败保留账本，只有完成结果推进来源游标。"""

        started_at = self._clock()
        previous_cursor = self._run_store.latest_cursor(
            subject_id, ConsolidationStage.L1_TO_L2,
        )
        batch = self._source_reader.read_batch(
            subject_id,
            after=previous_cursor,
            limit=self._config.maximum_sources_per_run,
        )
        start = ConsolidationRunCoordinator(
            self._run_store, config=self._config,
        ).try_start(
            subject_id=subject_id,
            stage=ConsolidationStage.L1_TO_L2,
            trigger=trigger,
            pending_source_count=batch.pending_new_source_count,
            selected_source_count=len(batch.sources) or None,
            now=started_at,
            budget_window_start=budget_window_start,
        )
        if start.run is None:
            return L1ToL2ConsolidationResult(start.decision, None)

        running = start.run
        inputs = tuple(ScenarioProposalInput(
            item.memory_id, item.subject_id, item.content, item.source_message_ids,
        ) for item in batch.sources)
        try:
            proposal = self._proposal.preview(inputs)
        except ScenarioProposalError as error:
            code = str(error)
            if code == "scenario_proposal_no_coherent_group":
                terminal = self._terminal(
                    running,
                    ConsolidationRunStatus.COMPLETED,
                    "no_coherent_group",
                    batch.next_cursor,
                )
            else:
                terminal = self._terminal(
                    running,
                    ConsolidationRunStatus.FAILED,
                    code or "scenario_proposal_failed",
                    None,
                )
            self._run_store.finish(terminal)
            return L1ToL2ConsolidationResult(start.decision, terminal)

        try:
            activated = self._activation.apply(
                proposal,
                inputs=inputs,
                risk=risk,
                generator_name=generator_name,
                generator_version=generator_version,
                generated_at=started_at,
            )
            terminal = self._terminal(
                running,
                ConsolidationRunStatus.COMPLETED,
                (
                    "scenario_activated"
                    if activated.scenario is not None
                    else "scenario_" + activated.decision.reason.value
                ),
                batch.next_cursor,
            )
            self._run_store.finish(terminal)
        except Exception:
            terminal = self._terminal(
                running,
                ConsolidationRunStatus.FAILED,
                "scenario_activation_failed",
                None,
            )
            self._run_store.finish(terminal)
            return L1ToL2ConsolidationResult(start.decision, terminal)
        return L1ToL2ConsolidationResult(
            start.decision, terminal, activated.decision, activated.scenario,
        )

    def _terminal(self, running, status, outcome, cursor):
        return ConsolidationRun(
            id=running.id,
            subject_id=running.subject_id,
            stage=running.stage,
            trigger=running.trigger,
            status=status,
            started_at=running.started_at,
            source_count=running.source_count,
            model_call_count=1,
            finished_at=self._clock(),
            outcome_code=outcome,
            cursor=cursor,
        )
