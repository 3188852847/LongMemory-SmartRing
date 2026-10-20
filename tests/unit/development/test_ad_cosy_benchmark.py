"""AD第二阶段评测入口的CPU门与真实HTTP/Opus；不运行GPU worker。"""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from test_ad_cosy_http_opus import ROOT, VOICE, PYTHON, _wave
from test_cosyvoice_service import service

SPEC = importlib.util.spec_from_file_location("ad_benchmark", ROOT / "scripts/development/cosyvoice/benchmark_ad_continuity.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)
CLIENT_SPEC = importlib.util.spec_from_file_location("ad_client", ROOT / "scripts/development/cosyvoice/benchmark_ad_client.py")
client = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_SPEC.loader.exec_module(client)


def receipt(now):
    return {"schema_version": 1, "scope": "ad-cosy-continuity", "window_id": "cpu-fixture-not-gpu-authorization",
            "exclusive_gpu": True, "production_stopped": True, "other_gpu_workers_stopped": True,
            "checkout": str(ROOT), "production_root": str(ROOT / "synthetic-production"),
            "candidate_commit": "a" * 40, "max_seconds": 480,
            "expires_at_utc": (now + timedelta(minutes=10)).isoformat()}


@pytest.mark.parametrize("change", [{"exclusive_gpu": False}, {"production_stopped": False},
    {"other_gpu_workers_stopped": False}, {"candidate_commit": "b" * 40},
    {"window_id": ""}, {"scope": "engine-compilation"}, {"max_seconds": 900},
    {"checkout": "D:/not-this-checkout"}, {"expires_at_utc": "invalid"},
    {"expires_at_utc": "2020-01-01T00:00:00+00:00"}, {"expires_at_utc": "2030-01-01T00:00:00"}])
def test_receipt_must_match_explicit_scope_checkout_commit_and_window(change):
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        bench.validate_receipt({**receipt(now), **change}, checkout=ROOT, commit="a" * 40,
            production=ROOT / "synthetic-production", seconds=480, now=now)


def test_valid_fixture_receipt_is_only_validation_and_does_not_create_lease():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert bench.validate_receipt(receipt(now), checkout=ROOT, commit="a" * 40,
        production=ROOT / "synthetic-production", seconds=480, now=now) is None


def test_live_gpu_occupancy_is_rejected_without_terminating_any_process():
    calls = []
    def query(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="1234, owner-daily-python.exe\n")
    with pytest.raises(RuntimeError, match="existing_gpu_compute"):
        bench.ensure_gpu_idle(query)
    assert len(calls) == 1 and calls[0][0] == "nvidia-smi"
    bench.ensure_gpu_idle(lambda *_args, **_kwargs: SimpleNamespace(stdout=""))


def test_plan_is_no_download_alternating_paired_matrix_with_three_real_cancel_boundaries():
    report = bench.plan()
    normal = [row for row in report["rows"] if row["cancel_stage"] is None]
    assert len(normal) == 12
    for start in range(0, 12, 2):
        pair = normal[start:start + 2]
        assert {row["mode"] for row in pair} == {"buffered", "adaptive"}
        assert pair[0]["seed"] == pair[1]["seed"]
        assert pair[0]["case"] == pair[1]["case"]
    assert {row["cancel_stage"] for row in report["rows"] if row["cancel_stage"]} == {
        "before_audio", "buffering", "after_audio"}
    assert report["engine_status"] == "needs_isolated_validation"
    assert report["new_downloads_required"] is False
    assert report["full_asr_memory_llm_chain_measured"] is False


def test_silence_and_single_spike_are_not_counted_as_first_voiced_frame():
    import struct
    assert not client.energy_qualified(b"\0" * 2880, 24000)
    assert not client.energy_qualified(struct.pack("<h", 20000) + b"\0" * 2878, 24000)
    assert client.energy_qualified(struct.pack("<h", 300) * 120 + b"\0" * 2640, 24000)


def test_summary_does_not_count_null_voice_or_cancel_sample_as_real_first_answer():
    row = {"case": "long", "mode": "adaptive", "cancel_stage": None,
           "server_generation_rtf": .7, "rounds": [{"first_opus_ms": 1200,
           "first_energy_qualified_opus_ms": None, "total_ms": 3000, "audio_ms": 4000,
           "estimated_supply_gap_ms": 120, "estimated_max_gap_ms": 100}]}
    result = bench.summarize([row, {**row, "cancel_stage": "after_audio"}])["long"]["adaptive"]
    assert result["first_opus_ms"] == {"samples": 1, "median": 1200, "max": 1200}
    assert result["first_energy_qualified_opus_ms"]["samples"] == 0
    assert result["first_energy_qualified_opus_ms"]["median"] is None


def test_worker_without_receipt_rejects_before_any_service_or_model_import(monkeypatch, tmp_path):
    monkeypatch.setattr(bench.subprocess, "check_output", lambda *_args, **_kwargs: b"a" * 40)
    import builtins
    original = builtins.__import__
    def checked(name, *args, **kwargs):
        if name in {"service", "torch", "cosyvoice"}:
            pytest.fail("model import before main-session receipt")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", checked)
    with pytest.raises(ValueError, match="exclusive_receipt"):
        bench.worker({"production": str(tmp_path), "output": str(tmp_path / "output"), "max_seconds": 480})


@pytest.mark.parametrize("failure", [None, "timeout", "assignment"])
def test_owned_worker_never_gets_permission_before_job_and_is_cleaned_on_failure(monkeypatch, tmp_path, failure):
    checkout, production = tmp_path / "checkout", tmp_path / "production"
    checkout.mkdir()
    cosy = production / "local/runtime/CosyVoice/.venv/Scripts/python.exe"
    voice = production / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe"
    for path in (cosy, voice):
        path.parent.mkdir(parents=True)
        path.touch()
    saved = receipt(datetime.now(timezone.utc))
    saved.update(checkout=str(checkout), production_root=str(production))
    receipt_path = tmp_path / "synthetic-receipt.json"
    receipt_path.write_text(json.dumps(saved), encoding="utf-8")
    actions = []
    class Job:
        def assign(self, process):
            if failure == "assignment":
                raise OSError("CPU fixture assignment failure")
            actions.append("assigned")
        def close(self):
            actions.append("job_closed")
    class Process:
        returncode = 0
        def communicate(self, data=None, **_kwargs):
            if data is not None:
                assert "assigned" in actions
                actions.append("worker_permitted")
                if failure == "timeout":
                    raise subprocess.TimeoutExpired("CPU fixture worker", 1)
            return b"CPU fixture stdout", b""
        def poll(self):
            return None if failure == "assignment" else 0
        def terminate(self):
            actions.append("unassigned_child_terminated")
        def wait(self, **_kwargs):
            actions.append("reaped")
    class Loader:
        def exec_module(self, module):
            module.Job = Job
    monkeypatch.setattr(bench, "ROOT", checkout)
    monkeypatch.setattr(bench, "ensure_gpu_idle", lambda: None)
    monkeypatch.setattr(bench.subprocess, "check_output", lambda command, **_kwargs:
        b"" if "status" in command else b"a" * 40)
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(bench.importlib.util, "spec_from_file_location", lambda *_args: SimpleNamespace(loader=Loader()))
    monkeypatch.setattr(bench.importlib.util, "module_from_spec", lambda _spec: SimpleNamespace())
    args = SimpleNamespace(production_root=production, output=checkout / "data/test-tmp/run",
                           receipt=receipt_path, cosy_python=cosy, max_seconds=480)
    if failure:
        with pytest.raises((subprocess.TimeoutExpired, OSError)):
            bench.execute(args)
    else:
        bench.execute(args)
    assert "job_closed" in actions and "reaped" in actions
    if failure == "assignment":
        assert "worker_permitted" not in actions and "unassigned_child_terminated" in actions
    else:
        assert actions.index("assigned") < actions.index("worker_permitted") < actions.index("job_closed")
    assert (args.output / "worker.stdout.log").read_bytes() == b"CPU fixture stdout"
    if failure == "timeout":
        assert json.loads((args.output / "deadline.json").read_text())["result"] == "owned_job_deadline_exceeded"


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed voice interpreter unavailable")
@pytest.mark.parametrize("mode,stage", [("buffered", None), ("adaptive", None),
    ("adaptive", "before_audio"), ("adaptive", "buffering"), ("adaptive", "after_audio")])
def test_real_http_client_reaches_cancel_boundary_then_plays_new_round(mode, stage):
    calls = []
    chunks = [_wave(0, 1440), _wave(1440, 10080), _wave(11520, 2880)]
    def stream(_text, *, cancel_event, model_streaming, use_cache):
        calls.append((model_streaming, use_cache))
        for chunk in chunks:
            if cancel_event.wait(.03):
                return
            yield chunk
    synth = SimpleNamespace(stream_chunks=stream,
        stream_runtime=SimpleNamespace(applied=True, snapshot=lambda: {"active_requests": 0}))
    server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    config = {"source_root": str(ROOT), "voice_root": str(VOICE), "mode": mode,
              "url": f"http://127.0.0.1:{server.server_address[1]}/v1/audio/stream",
              "text": "这是合成边界测试。", "cache": False, "sample_rate": 24000,
              "segmented": False, "cancel_stage": stage}
    try:
        result = subprocess.run([str(PYTHON), "-B", "-X", "utf8",
            str(ROOT / "scripts/development/cosyvoice/benchmark_ad_client.py")],
            input=json.dumps(config).encode(), capture_output=True, cwd=ROOT, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-3000:]
        report = json.loads(result.stdout)
        assert report["rounds"][-1]["opus_frames"] == 10
        assert report["rounds"][-1]["first_energy_qualified_opus_ms"] is not None
        assert "rtf" not in report["rounds"][-1]
        assert report["rounds"][-1]["client_tts_wall_rtf"] > 0
        assert report["rounds"][-1]["estimated_playback_end_ms"] == pytest.approx(
            report["rounds"][-1]["first_opus_ms"] + 600)
        assert len(report["rounds"]) == (2 if stage else 1)
        if stage:
            assert report["rounds"][0]["opus_frames"] == (3 if stage == "after_audio" else 0)
            assert report["rounds"][0]["packets_after_cancel"] == 0
            assert report["rounds"][0]["cancel_to_client_return_ms"] is not None
        if mode == "adaptive":
            assert all(item["reader_stopped"] for item in report["continuity"])
        assert report["llm_first_output_used_as_text"] is False
        assert report["gpu_work_performed"] is False
        assert all(not cached for _, cached in calls)
    finally:
        server.shutdown()
        server.server_close()
        serving.join(2)
