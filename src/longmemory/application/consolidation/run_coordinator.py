"""把持久账本状态转换为一次可执行、受预算约束的整理运行。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from longmemory.core.memory.consolidation.contracts import ConsolidationRunStore
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
    ConsolidationTriggerReason,
    ConsolidationTriggerState,
    decide_consolidation_trigger,
)


@dataclass(frozen=True, slots=True)
class ConsolidationStartResult:
    decision: ConsolidationTriggerDecision
    run: ConsolidationRun | None


class ConsolidationRunCoordinator:
    """读取账本并原子占用阶段槽位；实际模型调用由后续执行器负责。"""

    def __init__(
        self,
        store: ConsolidationRunStore,
        *,
        config: ConsolidationTriggerConfig = ConsolidationTriggerConfig(),
    ) -> None:
        self._store = store
        self._config = config

    def try_start(
        self,
        *,
        subject_id: str,
        stage: ConsolidationStage,
        trigger: ConsolidationTrigger,
        pending_source_count: int,
        now: datetime,
        budget_window_start: datetime,
    ) -> ConsolidationStartResult:
        """允许时创建 running 记录；并发抢占失败返回稳定 BLOCK 结果。"""

        if budget_window_start.tzinfo is None or budget_window_start.utcoffset() is None:
            raise ValueError("budget_window_start_timezone_required")
        recent = self._store.list_recent(subject_id, stage, limit=100)
        last_finished_at = next(
            (item.finished_at for item in recent if item.finished_at is not None),
            None,
        )
        decision = decide_consolidation_trigger(
            trigger=trigger,
            state=ConsolidationTriggerState(
                pending_source_count=pending_source_count,
                model_calls_today=self._store.model_calls_since(
                    subject_id, stage, budget_window_start,
                ),
                running=self._store.has_running(subject_id, stage),
                last_finished_at=last_finished_at,
            ),
            now=now,
            config=self._config,
        )
        if decision.action != ConsolidationTriggerAction.RUN:
            return ConsolidationStartResult(decision, None)

        run = ConsolidationRun(
            id=str(uuid4()),
            subject_id=subject_id,
            stage=stage,
            trigger=trigger,
            status=ConsolidationRunStatus.RUNNING,
            started_at=now,
            source_count=decision.source_limit,
        )
        try:
            self._store.start(run)
        except ValueError as error:
            if str(error) != "consolidation_already_running":
                raise
            raced = ConsolidationTriggerDecision(
                ConsolidationTriggerAction.BLOCK,
                ConsolidationTriggerReason.RUN_ALREADY_ACTIVE,
            )
            return ConsolidationStartResult(raced, None)
        return ConsolidationStartResult(decision, run)
