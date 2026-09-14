import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_input_latency.py"
SPEC = importlib.util.spec_from_file_location("voice_input_latency_test", SCRIPT)
input_latency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(input_latency)


def test_asr_wrapper_exposes_only_bounded_timings(monkeypatch):
    calls = []

    class Provider:
        async def handle_voice_stop(self, connection, audio):
            await module.startToChat(connection, "private transcript")

    async def start(connection, text):
        calls.append(text)

    module = SimpleNamespace(ASRProviderBase=Provider, startToChat=start)
    wall = iter([100.8])
    ticks = iter([1.0, 1.25, 1.26])
    monkeypatch.setattr(input_latency.time, "time", lambda: next(wall))
    monkeypatch.setattr(input_latency.time, "perf_counter", lambda: next(ticks))
    input_latency.install_voice_input_latency(module)
    connection = SimpleNamespace(vad_last_voice_time=100_000)
    asyncio.run(Provider().handle_voice_stop(connection, [b"private audio"]))
    assert calls == ["private transcript"]
    pending = connection._longmemory_voice_input_pending
    assert pending["input_timings_ms"] == {
        "vad_endpoint_ms": 800, "asr_processing_ms": 250,
    }
    assert "private" not in repr(pending)
