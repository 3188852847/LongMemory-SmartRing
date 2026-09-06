"""整理协调器读取持久状态并只为获准运行创建账本记录。"""

from datetime import UTC, datetime, timedelta

from longmemory.application.consolidation.run_coordinator import (
    ConsolidationRunCoordinator,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerAction,
    ConsolidationTriggerReason,
)


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self, *, calls=0, running=False, recent=(), race=False):
        self.calls, self.running, self.recent, self.race = calls, running, recent, race
        self.started = []

    def list_recent(self, subject_id, stage, *, limit=20):
        return self.recent

    def model_calls_since(self, subject_id, stage, since):
        return self.calls

    def has_running(self, subject_id, stage):
        return self.running

    def start(self, run):
        if self.race:
            raise ValueError("consolidation_already_running")
        self.started.append(run)


def start(store, pending=4):
    return ConsolidationRunCoordinator(store).try_start(
        subject_id="user:self",
        stage=ConsolidationStage.L1_TO_L2,
        trigger=ConsolidationTrigger.NEW_EVIDENCE,
        pending_source_count=pending,
        now=NOW,
        budget_window_start=NOW.replace(hour=0),
    )


def test_allowed_run_is_reserved_in_ledger():
    store = FakeStore()
    result = start(store, pending=9)
    assert result.decision.action == ConsolidationTriggerAction.RUN
    assert result.run is store.started[0]
    assert result.run.status == ConsolidationRunStatus.RUNNING
    assert result.run.source_count == 9


def test_held_decision_does_not_write_run():
    store = FakeStore()
    result = start(store, pending=2)
    assert result.decision.reason == ConsolidationTriggerReason.BELOW_SOURCE_THRESHOLD
    assert result.run is None and store.started == []


def test_concurrent_reservation_race_becomes_explainable_block():
    result = start(FakeStore(race=True))
    assert result.run is None
    assert (result.decision.action, result.decision.reason) == (
        ConsolidationTriggerAction.BLOCK,
        ConsolidationTriggerReason.RUN_ALREADY_ACTIVE,
    )


def test_recent_terminal_run_applies_cooldown():
    # 失败没有游标，但同样需要冷却，避免短时间内形成故障重试风暴。
    failed = ConsolidationRun(
        "failed", "user:self", ConsolidationStage.L1_TO_L2,
        ConsolidationTrigger.NEW_EVIDENCE, ConsolidationRunStatus.FAILED,
        NOW - timedelta(minutes=10), source_count=4, model_call_count=1,
        finished_at=NOW - timedelta(minutes=5), outcome_code="model_request_failed",
    )
    result = start(FakeStore(recent=(failed,)))
    assert result.decision.reason == ConsolidationTriggerReason.COOLDOWN_ACTIVE
