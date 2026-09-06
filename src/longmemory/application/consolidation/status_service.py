"""把整理账本与待处理来源投影成控制台可读状态。"""

from dataclasses import dataclass
from datetime import UTC, datetime

from longmemory.core.memory.consolidation.contracts import (
    ConsolidationRunStore,
    L1ConsolidationSourceReader,
    L2ConsolidationSourceReader,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationCursor,
    ConsolidationRun,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerConfig,
    ConsolidationTriggerState,
    decide_consolidation_trigger,
)


@dataclass(frozen=True, slots=True)
class ConsolidationStageStatus:
    stage: ConsolidationStage
    pending_new_source_count: int
    trigger_action: str
    trigger_reason: str
    minimum_new_sources: int
    maximum_sources_per_run: int
    cooldown_seconds: int
    daily_model_call_budget: int
    model_calls_today: int
    cursor: ConsolidationCursor | None
    latest_run: ConsolidationRun | None


class ConsolidationStatusService:
    """只读解释当前状态；不会恢复任务、调用模型或写入记忆。"""

    def __init__(
        self,
        *,
        run_store: ConsolidationRunStore,
        l1_reader: L1ConsolidationSourceReader,
        l2_reader: L2ConsolidationSourceReader,
        l1_config: ConsolidationTriggerConfig,
        l2_config: ConsolidationTriggerConfig,
    ) -> None:
        self._runs = run_store
        self._l1_reader = l1_reader
        self._l2_reader = l2_reader
        self._configs = {
            ConsolidationStage.L1_TO_L2: l1_config,
            ConsolidationStage.L2_TO_L3: l2_config,
        }

    def inspect(
        self, subject_id: str, *, now: datetime,
    ) -> tuple[ConsolidationStageStatus, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_timezone_required")
        budget_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        result = []
        for stage in ConsolidationStage:
            config = self._configs[stage]
            cursor = self._runs.latest_cursor(subject_id, stage)
            if stage == ConsolidationStage.L1_TO_L2:
                batch = self._l1_reader.read_batch(
                    subject_id, after=cursor, limit=config.maximum_sources_per_run,
                )
            else:
                batch = self._l2_reader.read_batch(
                    subject_id, after=cursor, limit=config.maximum_sources_per_run,
                    now=now,
                )
            recent = self._runs.list_recent(subject_id, stage, limit=1)
            latest = recent[0] if recent else None
            calls = self._runs.model_calls_since(subject_id, stage, budget_start)
            decision = decide_consolidation_trigger(
                trigger=ConsolidationTrigger.NEW_EVIDENCE,
                state=self._state(batch.pending_new_source_count, calls, latest),
                now=now,
                config=config,
            )
            result.append(ConsolidationStageStatus(
                stage=stage,
                pending_new_source_count=batch.pending_new_source_count,
                trigger_action=decision.action.value,
                trigger_reason=decision.reason.value,
                minimum_new_sources=config.minimum_new_sources,
                maximum_sources_per_run=config.maximum_sources_per_run,
                cooldown_seconds=int(config.cooldown.total_seconds()),
                daily_model_call_budget=config.daily_model_call_budget,
                model_calls_today=calls,
                cursor=cursor,
                latest_run=latest,
            ))
        return tuple(result)

    @staticmethod
    def _state(pending, calls, latest):
        return ConsolidationTriggerState(
            pending_source_count=pending,
            model_calls_today=calls,
            running=latest is not None and latest.status.value == "running",
            last_finished_at=(latest.finished_at if latest is not None else None),
        )
