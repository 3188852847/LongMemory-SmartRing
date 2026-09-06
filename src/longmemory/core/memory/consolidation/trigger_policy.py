"""低频整理的确定性触发策略；不访问数据库，也不调用模型。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .models import ConsolidationTrigger


class ConsolidationTriggerAction(StrEnum):
    RUN = "run"
    HOLD = "hold"
    BLOCK = "block"


class ConsolidationTriggerReason(StrEnum):
    READY = "ready"
    MANUAL_READY = "manual_ready"
    NO_PENDING_EVIDENCE = "no_pending_evidence"
    BELOW_SOURCE_THRESHOLD = "below_source_threshold"
    COOLDOWN_ACTIVE = "cooldown_active"
    DAILY_BUDGET_EXHAUSTED = "daily_budget_exhausted"
    RUN_ALREADY_ACTIVE = "run_already_active"


@dataclass(frozen=True, slots=True)
class ConsolidationTriggerConfig:
    """产品运行护栏；数值可配置，不代表研究得到的最优阈值。"""

    minimum_new_sources: int = 4
    maximum_sources_per_run: int = 20
    cooldown: timedelta = timedelta(hours=6)
    daily_model_call_budget: int = 2

    def __post_init__(self) -> None:
        if (
            self.minimum_new_sources < 1
            or self.maximum_sources_per_run < self.minimum_new_sources
            or self.cooldown < timedelta(0)
            or self.daily_model_call_budget < 1
        ):
            raise ValueError("consolidation_trigger_config_invalid")


@dataclass(frozen=True, slots=True)
class ConsolidationTriggerState:
    pending_source_count: int
    model_calls_today: int
    running: bool = False
    last_finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.pending_source_count < 0 or self.model_calls_today < 0:
            raise ValueError("consolidation_trigger_state_invalid")
        if self.last_finished_at is not None and (
            self.last_finished_at.tzinfo is None
            or self.last_finished_at.utcoffset() is None
        ):
            raise ValueError("last_finished_at_timezone_required")


@dataclass(frozen=True, slots=True)
class ConsolidationTriggerDecision:
    action: ConsolidationTriggerAction
    reason: ConsolidationTriggerReason
    source_limit: int = 0
    policy_version: str = "consolidation-trigger-v1"


def decide_consolidation_trigger(
    *,
    trigger: ConsolidationTrigger,
    state: ConsolidationTriggerState,
    now: datetime,
    config: ConsolidationTriggerConfig = ConsolidationTriggerConfig(),
) -> ConsolidationTriggerDecision:
    """决定是否允许一次整理；人工触发也不能绕过互斥和调用预算。"""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_timezone_required")
    if state.running:
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.BLOCK,
            ConsolidationTriggerReason.RUN_ALREADY_ACTIVE,
        )
    if state.pending_source_count == 0:
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.NO_PENDING_EVIDENCE,
        )
    if state.model_calls_today >= config.daily_model_call_budget:
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.BLOCK,
            ConsolidationTriggerReason.DAILY_BUDGET_EXHAUSTED,
        )
    source_limit = min(state.pending_source_count, config.maximum_sources_per_run)
    if trigger == ConsolidationTrigger.MANUAL:
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.RUN,
            ConsolidationTriggerReason.MANUAL_READY,
            source_limit,
        )
    if state.pending_source_count < config.minimum_new_sources:
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.BELOW_SOURCE_THRESHOLD,
        )
    if (
        state.last_finished_at is not None
        and now - state.last_finished_at < config.cooldown
    ):
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.HOLD,
            ConsolidationTriggerReason.COOLDOWN_ACTIVE,
        )
    return ConsolidationTriggerDecision(
        ConsolidationTriggerAction.RUN,
        ConsolidationTriggerReason.READY,
        source_limit,
    )

