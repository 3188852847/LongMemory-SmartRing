"""无需模型或 CUDA，验证阶段计时保留原语义且可跨线程读取。"""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "cosyvoice_runtime_diagnostics_test",
    ROOT / "scripts/development/cosyvoice/runtime_diagnostics.py",
)
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


def test_stage_call_keeps_arguments_return_value_and_instance_scope(monkeypatch):
    ticks = iter([1.0, 1.125])
    monkeypatch.setattr(diagnostics, "perf_counter", lambda: next(ticks))
    seen = []
    expected = object()

    class Flow:
        def inference(self, value, *, finalize):
            seen.append((self, value, finalize, threading.get_ident()))
            return expected

    flow = Flow()
    untouched = Flow().inference.__func__
    model = SimpleNamespace(model=SimpleNamespace(flow=flow))
    tracker = diagnostics.install_runtime_diagnostics(model)

    assert flow.inference("synthetic input", finalize=False) is expected
    assert seen == [(flow, "synthetic input", False, threading.get_ident())]
    assert Flow().inference.__func__ is untouched
    assert tracker.snapshot() == {"flow": {"calls": 1, "wall_ms": 125.0}}


def test_failed_call_keeps_same_exception_and_counts_elapsed_time(monkeypatch):
    ticks = iter([2.0, 2.25])
    monkeypatch.setattr(diagnostics, "perf_counter", lambda: next(ticks))
    error = ValueError("synthetic failure")

    def fail():
        raise error

    runtime = SimpleNamespace(llm_job=fail)
    tracker = diagnostics.install_runtime_diagnostics(SimpleNamespace(model=runtime))
    with pytest.raises(ValueError) as caught:
        runtime.llm_job()
    assert caught.value is error
    assert tracker.snapshot() == {"llm_job": {"calls": 1, "wall_ms": 250.0}}


def test_all_four_stages_are_separate_and_snapshots_do_not_share_counters(monkeypatch):
    ticks = iter([1.0, 1.1, 2.0, 2.2, 3.0, 3.3, 4.0, 4.4])
    monkeypatch.setattr(diagnostics, "perf_counter", lambda: next(ticks))
    model = SimpleNamespace(
        model=SimpleNamespace(
            llm_job=lambda: None,
            flow=SimpleNamespace(inference=lambda: None),
            hift=SimpleNamespace(inference=lambda: None),
        ),
        frontend=SimpleNamespace(text_normalize=lambda text: text),
    )
    tracker = diagnostics.install_runtime_diagnostics(model)
    before = tracker.snapshot()
    model.model.llm_job()
    model.model.flow.inference()
    model.model.hift.inference()
    assert model.frontend.text_normalize("synthetic input") == "synthetic input"
    after = tracker.snapshot()

    assert after == {
        "llm_job": {"calls": 1, "wall_ms": 100.0},
        "flow": {"calls": 1, "wall_ms": 200.0},
        "hift": {"calls": 1, "wall_ms": 300.0},
        "text_normalize": {"calls": 1, "wall_ms": 400.0},
    }
    assert all(record == {"calls": 0, "wall_ms": 0.0} for record in before.values())
    after["flow"]["calls"] = 999
    assert tracker.snapshot()["flow"]["calls"] == 1


def test_concurrent_calls_and_health_snapshots_do_not_hold_model_lock():
    tracker = diagnostics.RuntimeDiagnostics()
    # 在被包装方法内部读取快照，验证累计值锁未覆盖原方法调用。
    def normalize(value):
        tracker.snapshot()
        return value, threading.get_ident()

    frontend = SimpleNamespace(text_normalize=normalize)
    tracker.wrap(frontend, "text_normalize", "text_normalize")
    caller = threading.get_ident()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(frontend.text_normalize, range(200)))

    assert [value for value, _ in results] == list(range(200))
    assert all(thread != caller for _, thread in results)
    assert tracker.snapshot()["text_normalize"]["calls"] == 200
    assert tracker.snapshot()["text_normalize"]["wall_ms"] >= 0


def test_missing_and_lazy_methods_are_left_unchanged():
    def generator():
        yield "synthetic"

    async def coroutine():
        return "synthetic"

    runtime = SimpleNamespace(llm_job=generator, flow=SimpleNamespace(inference=coroutine))
    tracker = diagnostics.install_runtime_diagnostics(SimpleNamespace(model=runtime))
    assert tracker.snapshot() == {}
    assert runtime.llm_job is generator
    assert runtime.flow.inference is coroutine
    assert diagnostics.install_runtime_diagnostics(None).snapshot() == {}
