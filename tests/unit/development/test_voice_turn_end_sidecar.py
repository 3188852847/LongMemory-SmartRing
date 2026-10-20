"""真实专属子进程/匿名管道验证，不加载模型、GPU 或日用服务。"""

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
SPEC = importlib.util.spec_from_file_location("voice_turn_end_sidecar_ac_test", SCRIPTS / "voice_turn_end_sidecar.py")
sidecar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sidecar
SPEC.loader.exec_module(sidecar)
PCM = b"\x01\x00" * 16000


def command(mode="normal"):
    return [sys.executable, "-I", "-B", "-u", str(ROOT / "tests/fixtures/voice_turn_end_sidecar_worker.py"), "--mode", mode]


def make_client(mode="normal", **kwargs):
    return sidecar.SidecarDetector(sys.executable, "not-used.onnx", _command=command(mode), **kwargs)


def test_cpu_child_environment_does_not_mutate_parent(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "must-not-inherit")
    monkeypatch.setenv("PYTHONHOME", "must-not-inherit")
    monkeypatch.setenv("USE_TORCH", "original")
    environment = sidecar.cpu_environment()
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert environment["USE_TORCH"] == "0"
    assert sidecar.os.environ["USE_TORCH"] == "original"
    assert sidecar.os.environ["PYTHONPATH"] == "must-not-inherit"


def test_persistent_real_process_reuses_one_pid_and_preserves_payload_privacy(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "must-not-inherit")
    client = make_client(request_timeout_ms=500)
    try:
        pid = client.process.pid
        for _ in range(3):
            assert client.predict(PCM) == 0.9
            assert client.process.pid == pid
        result = client.snapshot()
        assert result["completed"] == 3
        assert result["ready"]
        assert "pcm" not in str(result)
        assert client.sequence == 3
    finally:
        client.close()
    assert client.process.poll() is not None
    assert not client.io_thread.is_alive()
    client.close()


def test_async_start_and_inference_do_not_block_event_loop():
    async def run():
        client = await sidecar.SidecarDetector.create(sys.executable, "unused", _command=command("brief"), request_timeout_ms=500)
        ticks = 0
        task = asyncio.create_task(asyncio.to_thread(client.predict, PCM))
        try:
            while not task.done():
                ticks += 1
                await asyncio.sleep(0.002)
            assert await task == 0.9
            assert ticks >= 5
        finally:
            await client.aclose()
        assert client.process.poll() is not None
    asyncio.run(run())


def test_timeout_terminates_only_owned_process_and_disables_no_retry():
    client = make_client("slow", request_timeout_ms=30)
    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="sidecar_timeout"):
            client.predict(PCM)
        assert time.monotonic() - started < 0.3
        with pytest.raises(RuntimeError, match="sidecar_disabled"):
            client.predict(PCM)
        assert client.snapshot()["timeout"] == 1
        assert not client.snapshot()["ready"]
    finally:
        client.close()
    assert client.process.poll() is not None


def test_concurrent_request_is_rejected_without_queue_or_new_process():
    client = make_client("brief", request_timeout_ms=500)
    results = []
    thread = threading.Thread(target=lambda: results.append(client.predict(PCM)))
    try:
        thread.start()
        deadline = time.monotonic() + 1
        while not client.serial.locked() and time.monotonic() < deadline:
            time.sleep(0.001)
        with pytest.raises(RuntimeError, match="sidecar_busy"):
            client.predict(PCM)
        thread.join(timeout=1)
        assert results == [0.9]
        assert client.sequence == 1
    finally:
        client.close()
        thread.join(timeout=1)


@pytest.mark.parametrize("mode", ["wrongid", "error"])
def test_bad_worker_result_is_terminal_and_sanitized(mode):
    client = make_client(mode, request_timeout_ms=500)
    try:
        with pytest.raises(RuntimeError, match="^turn_end_sidecar_failed$"):
            client.predict(PCM)
        assert not client.snapshot()["ready"]
        assert client.snapshot()["failed"] == 1
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["unavailable", "nohandshake"])
def test_startup_failure_reaps_child(monkeypatch, mode):
    children = []
    original = sidecar.subprocess.Popen
    def capture(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(sidecar.subprocess, "Popen", capture)
    with pytest.raises(RuntimeError, match="sidecar_unavailable"):
        make_client(mode, startup_timeout=1)
    assert len(children) == 1
    assert children[0].poll() is not None


def test_cancel_async_startup_reaps_late_child(monkeypatch):
    children = []
    original = sidecar.subprocess.Popen
    def capture(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(sidecar.subprocess, "Popen", capture)
    async def run():
        task = asyncio.create_task(sidecar.SidecarDetector.create(
            sys.executable, "unused", _command=command("nohandshake")))
        while not children:
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 2
        while children[0].poll() is None and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
    asyncio.run(run())
    assert children[0].poll() is not None


@pytest.mark.parametrize("payload", [b"", b"x", b"\x00" * 256002, "not bytes"],
                         ids=["empty", "odd", "oversized", "wrong_type"])
def test_payload_budget_rejected_without_request(payload):
    client = make_client()
    try:
        with pytest.raises(ValueError, match="pcm_budget"):
            client.predict(payload)
        assert client.sequence == 0
    finally:
        client.close()


def test_worker_protocol_rejects_oversized_or_wrong_magic_without_echo():
    class Detector:
        def predict(self, pcm):
            pytest.fail("invalid request reached model")
    for header in (sidecar.HEADER.pack(b"BAD!", 1, 2), sidecar.HEADER.pack(sidecar.MAGIC, 1, 256002)):
        sink = io.BytesIO()
        assert sidecar.worker_loop(Detector(), io.BytesIO(header), sink) == 2
        assert json.loads(sink.getvalue())["status"] == "ready"


def test_missing_model_fails_closed_before_runtime_import():
    # 使用当前测试解释器即可验证缺文件错误在加载依赖之前即被净化。
    process = subprocess.run([sys.executable, "-I", "-B", str(SCRIPTS / "voice_turn_end_sidecar.py"),
                              "--probe-model", "--model", str(ROOT / "data/test-tmp/nonexistent-ac-model.onnx")],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert process.returncode == 2
    assert json.loads(process.stdout) == {"version": 1, "status": "unavailable", "reason": "model_or_runtime_unavailable"}
    assert b"nonexistent" not in process.stdout
