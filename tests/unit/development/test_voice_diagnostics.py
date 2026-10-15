"""合成并发轮次、线程交接、观测降级；不加载模型或操作设备。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import queue
import ast
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"
sys.path.insert(0, str(DIRECTORY))
import voice_diagnostics as diagnostic
import voice_latency
import voice_input_latency

from longmemory.infrastructure.logging.diagnostics import Diagnostics, VOICE_EVENTS


def test_protocol_allowlists_match_and_bounded_late_events_do_not_change_other_round(monkeypatch):
    assert diagnostic.EVENTS == VOICE_EVENTS
    observer = Diagnostics(capacity=2)
    monkeypatch.setattr(diagnostic, "emit", observer.voice_event)
    old, new = diagnostic.VoiceRound(), diagnostic.VoiceRound()
    old.event("chat_entered")
    old.event("cancelled")
    new.event("chat_entered")
    old.event("tts_audio_ready")
    for _ in range(500):
        new.event("model_output")
    rows = {row["round_id"]: row for row in observer.voice_snapshot()["rounds"]}
    assert rows[old.round_id]["state"] == "cancelled"
    assert len(rows[new.round_id]["events"]) == 2
    assert "tts_audio_ready" not in {event["event"] for event in rows[new.round_id]["events"]}
    assert rows[new.round_id]["device_playback"] == "unconfirmed"
    observer.voice_event({"round_id": new.round_id, "event": "tts_failed", "sequence": 4})
    assert observer.voice_snapshot()["rounds"][0]["sequence_gaps"] == [3]


def test_asr_context_is_explicitly_copied_to_the_same_executor_and_isolated(monkeypatch):
    seen, events = [], []
    monkeypatch.setattr(diagnostic, "emit", events.append)
    monkeypatch.setattr(voice_latency, "_observe_components", lambda _connection: None)

    class Connection:
        def __init__(self, executor):
            self.executor = executor
            self.config = {}
            self.logger = SimpleNamespace(bind=lambda **kw: SimpleNamespace(info=lambda line: None))
            self.sentence_id = None

        def chat(self, text, depth=0):
            trace = diagnostic.CURRENT.get()
            seen.append((text, trace.round_id))
            self.sentence_id = text  # 仅合成身份，摘要里不得出现。
            self._longmemory_voice_latency.bind_sentence()
            assert diagnostic.for_sentence(self, text) is trace
            return "synthetic-answer"

    class Provider:
        async def handle_voice_stop(self, connection, audio):
            return await module.startToChat(connection, audio)

    async def start(connection, text):
        return await asyncio.wrap_future(connection.executor.submit(connection.chat, text))

    module = SimpleNamespace(ASRProviderBase=Provider, startToChat=start)
    voice_latency.install_voice_latency(Connection)
    voice_input_latency.install_voice_input_latency(module)

    async def run(executor):
        connections = [Connection(executor) for _ in range(2)]
        result = await asyncio.gather(*[Provider().handle_voice_stop(connection, f"private-input-{index}")
                                        for index, connection in enumerate(connections)])
        assert result == ["synthetic-answer"] * 2
        assert all(connection.executor.executor is executor for connection in connections)
        assert diagnostic.CURRENT.get() is None

    with ThreadPoolExecutor(max_workers=2) as executor:
        asyncio.run(run(executor))
    assert len({round_id for _, round_id in seen}) == 2
    for _, round_id in seen:
        names = {event["event"] for event in events if event["round_id"] == round_id}
        assert {"asr_entered", "asr_handoff", "chat_entered", "chat_returned"} <= names
    assert "private-input" not in repr(events)


def test_context_absent_or_missing_executor_does_not_guess_asr_association(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostic, "emit", events.append)
    diagnostic.event("model_requested")
    assert diagnostic.headers() == {} and events == []
    assert diagnostic.for_sentence(SimpleNamespace(_longmemory_diagnostic_round=diagnostic.VoiceRound()), "missing") is None


def test_queue_saturation_or_observer_failure_does_not_raise_or_retry_business(monkeypatch):
    full = queue.Queue(1)
    full.put("occupied")
    monkeypatch.setattr(diagnostic, "_queue", full)
    monkeypatch.setattr(diagnostic, "_worker", object())
    monkeypatch.setattr(diagnostic, "_target", lambda: ("synthetic-unused", "a" * 64))
    before = diagnostic._dropped
    diagnostic.VoiceRound().event("model_requested")
    assert diagnostic._dropped == before + 1 and full.qsize() == 1
    monkeypatch.setattr(diagnostic, "emit", lambda _: (_ for _ in ()).throw(RuntimeError("private-secret")))
    diagnostic.VoiceRound().event("model_requested")


def test_model_generator_uses_captured_round_after_context_has_changed(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostic, "emit", events.append)
    old, new = diagnostic.VoiceRound(), diagnostic.VoiceRound()
    connection = SimpleNamespace(_longmemory_voice_latency=SimpleNamespace(mark=lambda *a, **kw: None))
    iterator = voice_latency._observe_generator(connection, iter(["private-model-answer"]), trace=old)
    token = diagnostic.CURRENT.set(new)
    try:
        assert list(iterator) == ["private-model-answer"]
    finally:
        diagnostic.CURRENT.reset(token)
    assert {event["round_id"] for event in events} == {old.round_id}
    assert {event["event"] for event in events} == {"model_output", "model_returned"}
    assert "private" not in repr(events)


def test_timeout_and_generator_close_are_explicit_without_error_text(monkeypatch):
    events = []
    monkeypatch.setattr(diagnostic, "emit", events.append)
    trace = diagnostic.VoiceRound()
    tracker = SimpleNamespace(mark=lambda *a, **kw: None, fail=lambda code: None)
    connection = SimpleNamespace(_longmemory_voice_latency=tracker)
    def timeout():
        raise TimeoutError("private-key-and-text")
        yield
    with pytest.raises(TimeoutError):
        list(voice_latency._observe_generator(connection, timeout(), trace=trace))
    assert events[-1]["event"] == "model_timeout" and "private" not in repr(events)
    iterator = voice_latency._observe_generator(connection, iter(["one", "two"]), trace=trace)
    assert next(iterator) == "one"
    iterator.close()
    assert events[-1]["event"] == "cancelled"


@pytest.mark.parametrize("url", [
    "http://example.invalid/api/internal/memory/prepare", "https://127.0.0.1:12345/api/internal/memory/prepare",
    "http://127.0.0.1:12345/other", "http://user:password@127.0.0.1:12345/api/internal/memory/prepare",
    "http://127.0.0.1:12345/api/internal/memory/prepare?secret=value",
])
def test_observer_never_targets_arbitrary_urls(monkeypatch, url):
    monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", url)
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "a" * 64)
    assert diagnostic._target() is None


def test_wrapper_sources_keep_python310_syntax():
    for name in ("voice_diagnostics.py", "voice_latency.py", "voice_input_latency.py", "longmemory_provider.py",
                 "cosyvoice_streaming.py", "launch_with_memory.py"):
        ast.parse((DIRECTORY / name).read_text(encoding="utf-8"), feature_version=(3, 10))
    ast.parse((DIRECTORY.parent / "cosyvoice/service.py").read_text(encoding="utf-8"), feature_version=(3, 10))


def test_observation_redirect_is_not_followed_with_bearer():
    visits = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            visits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/must-not-visit")
            self.end_headers()
        def do_GET(self):
            visits.append(self.path)
            self.send_response(200)
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = Request(f"http://127.0.0.1:{server.server_address[1]}/observe", data=b"{}",
                          headers={"Authorization": "Bearer synthetic"})
        with pytest.raises(HTTPError):
            build_opener(ProxyHandler({}), diagnostic.NoRedirect()).open(request, timeout=2)
        assert visits == ["/observe"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


@pytest.mark.parametrize("update", [
    {"event": "private transcript"}, {"round_id": "client-secret"}, {"sequence": True},
    {"http_request_id": "private-id"}, {"transcript": "secret"},
])
def test_receiver_rejects_nonwhitelist_payloads(update):
    with pytest.raises(ValueError):
        Diagnostics().voice_event({"round_id": "a" * 24, "event": "chat_entered", "sequence": 1, **update})
