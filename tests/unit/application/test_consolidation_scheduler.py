"""唯一后台整理调度器与 MemoryRuntime 的非阻塞生命周期回归。"""

from pathlib import Path
from threading import Event

from longmemory.application.consolidation.scheduler import (
    LowFrequencyConsolidationScheduler,
)
from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.methods.contracts import (
    MemorySupport,
    MethodCapabilities,
    ObservationResult,
    WriteTrace,
)


class WritingMethod:
    name = "synthetic"
    implementation_version = "1"
    capabilities = MethodCapabilities()

    def __init__(self):
        self.closed = False

    def observe(self, event):
        return ObservationResult(
            event.event_id,
            (WriteTrace("add", "l1-a", (event.event_id,)),),
        )

    def archive(self, event):
        return ObservationResult(event.event_id, ())

    def recall(self, _query):
        return MemorySupport("call-a", "", ())

    def wait_until_ready(self):
        return None

    def close(self):
        self.closed = True


def test_disabled_scheduler_never_starts_or_runs():
    calls = []
    scheduler = LowFrequencyConsolidationScheduler(
        subject_id="user:self", run_cycle=lambda subject: calls.append(subject),
    )

    assert scheduler.notify_new_evidence() is False
    assert calls == []
    assert scheduler.status().enabled is False
    assert scheduler.close() is True


def test_notifications_during_a_cycle_are_coalesced_into_one_follow_up():
    first_started = Event()
    release_first = Event()
    second_finished = Event()
    calls = []

    def run_cycle(subject):
        calls.append(subject)
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(2)
        else:
            second_finished.set()
        return "checked"

    scheduler = LowFrequencyConsolidationScheduler(
        subject_id="user:self", run_cycle=run_cycle, enabled=True,
    )
    try:
        assert scheduler.notify_new_evidence()
        assert first_started.wait(2)
        assert scheduler.notify_new_evidence()
        assert scheduler.notify_new_evidence()
        release_first.set()
        assert second_finished.wait(2)
        assert calls == ["user:self", "user:self"]
    finally:
        release_first.set()
        assert scheduler.close()


def test_runtime_returns_before_background_cycle_finishes_and_owns_close():
    cycle_started = Event()
    release_cycle = Event()

    def run_cycle(_subject):
        cycle_started.set()
        assert release_cycle.wait(2)
        return "checked"

    scheduler = LowFrequencyConsolidationScheduler(
        subject_id="user:self", run_cycle=run_cycle, enabled=True,
    )
    method = WritingMethod()
    runtime = MemoryRuntime(
        Path("synthetic.db"), method=method,
        consolidation_scheduler=scheduler,
    )
    prepared = runtime.prepare_user("我喜欢乌龙茶")
    assert prepared.observation.writes
    assert cycle_started.wait(2)
    assert scheduler.status().running is True
    release_cycle.set()
    runtime.close()
    assert method.closed is True
    assert scheduler.status().closed is True
