"""只读状态必须解释门槛、预算和最近运行，且不产生写入。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from longmemory.application.consolidation.status_service import ConsolidationStatusService
from longmemory.core.memory.consolidation.models import (
    ConsolidationRun,
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.trigger_policy import (
    ConsolidationTriggerConfig,
)


NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


class FakeRuns:
    def __init__(self, recent=()):
        self.recent = recent

    def latest_cursor(self, subject_id, stage):
        return None

    def list_recent(self, subject_id, stage, *, limit=20):
        return tuple(item for item in self.recent if item.stage == stage)[:limit]

    def model_calls_since(self, subject_id, stage, since):
        return sum(item.model_call_count for item in self.recent if item.stage == stage)


class FakeReader:
    def __init__(self, pending):
        self.pending = pending

    def read_batch(self, subject_id, **kwargs):
        return SimpleNamespace(pending_new_source_count=self.pending)


def service(runs=()):
    return ConsolidationStatusService(
        run_store=FakeRuns(runs),
        l1_reader=FakeReader(3),
        l2_reader=FakeReader(2),
        l1_config=ConsolidationTriggerConfig(),
        l2_config=ConsolidationTriggerConfig(
            minimum_new_sources=2,
            maximum_sources_per_run=12,
            cooldown=timedelta(hours=24),
            daily_model_call_budget=2,
            model_calls_per_run=2,
        ),
    )


def test_status_explains_threshold_and_ready_stage():
    l1, l2 = service().inspect("user:self", now=NOW)
    assert (l1.trigger_action, l1.trigger_reason) == (
        "hold", "below_source_threshold",
    )
    assert l1.pending_new_source_count == 3
    assert (l2.trigger_action, l2.trigger_reason) == ("run", "ready")
    assert l2.daily_model_call_budget == 2


def test_running_stage_is_exposed_as_blocked():
    running = ConsolidationRun(
        "run-1", "user:self", ConsolidationStage.L2_TO_L3,
        ConsolidationTrigger.NEW_EVIDENCE, ConsolidationRunStatus.RUNNING,
        NOW - timedelta(minutes=5), source_count=2,
    )
    _l1, l2 = service((running,)).inspect("user:self", now=NOW)
    assert (l2.trigger_action, l2.trigger_reason) == (
        "block", "run_already_active",
    )
    assert l2.latest_run is running
