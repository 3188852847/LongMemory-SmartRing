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
    RISK_ASSESSMENT_INCOMPLETE = "risk_assessment_incomplete"


@dataclass(frozen=True, slots=True)
class ConsolidationTriggerConfig:
    """产品运行护栏；数值可配置，不代表研究得到的最优阈值。"""

    minimum_new_sources: int = 4
    maximum_sources_per_run: int = 20
    cooldown: timedelta = timedelta(hours=6)
    daily_model_call_budget: int = 2
    # 一次非 NOOP 整理包含“生成候选 + 独立风险复核”两次调用。触发前按
    # 最坏情况预留，避免先生成后才发现当天已没有复核预算。
    model_calls_per_run: int = 2

    def __post_init__(self) -> None:
        if (
            self.minimum_new_sources < 1
            or self.maximum_sources_per_run < self.minimum_new_sources
            or self.cooldown < timedelta(0)
            or self.daily_model_call_budget < 1
            or not 1 <= self.model_calls_per_run <= self.daily_model_call_budget
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
    if (
        state.model_calls_today + config.model_calls_per_run
        > config.daily_model_call_budget
    ):
        return ConsolidationTriggerDecision(
            ConsolidationTriggerAction.BLOCK,
            ConsolidationTriggerReason.DAILY_BUDGET_EXHAUSTED,
        )
    # 返回整批容量而不是仅返回“新来源数”；调用方可在余量中带入游标前
    # 仍未归组的旧来源，让它们有机会与新证据形成场景。
    source_limit = config.maximum_sources_per_run
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
