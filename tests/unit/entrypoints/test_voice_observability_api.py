"""真实子进程 → 内部认证 HTTP → 记忆审计；仅合成后端和临时端口。"""

import asyncio
import importlib.util
from dataclasses import dataclass
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace as Namespace

import aiohttp
from aiohttp import web

from longmemory.entrypoints.api.observability import observability_middleware, register_observability
from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.infrastructure.logging.diagnostics import Diagnostics
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging, log_event


@dataclass
class Timings:
    lock_wait_ms: int = 0
    command_ms: int = 0
    observe_ms: int = 0
    recall_ms: int = 0
    scenario_ms: int = 0
    persona_ms: int = 0
    total_ms: int = 0


class Backend:
    def prepare_round_screen_user(self, text):
        assert text == "private synthetic transcript"
        log_event("context_built", turn_id="synthetic-turn", count=0)
        return Namespace(
            support=Namespace(context="private synthetic context", retrieved=[], retrieval_strategy="synthetic", warning_code=None),
            observation=Namespace(writes=[], processing_status="completed", warning_code=None),
            scenarios=[], personas=[], memory_command=None, follow_up_suggestion=None, temporary_interaction=None,
            event=Namespace(event_id="11111111-1111-1111-1111-111111111111"), timings=Timings(),
            write_enabled=False, use_enabled=True, scenario_use_enabled=False, persona_use_enabled=False,
        ), None


def test_subprocess_explicit_round_and_server_http_id_with_auth_and_safe_summary(tmp_path, monkeypatch):
    async def run():
        observer = Diagnostics(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        audit = configure_file_logging(audit_path)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        app = web.Application(middlewares=[observability_middleware(observer),
            security_middleware(f"127.0.0.1:{port}", Sessions(), "a" * 64)])
        register_observability(app, observer)
        register_memory_runtime_routes(app, Backend())
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        source = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"
        monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", origin + "/api/internal/memory/prepare")
        monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "a" * 64)
        monkeypatch.syspath_prepend(str(source.parent / "cosyvoice"))
        spec = importlib.util.spec_from_file_location("synthetic_q_cosyvoice", source.parent / "cosyvoice/service.py")
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)
        class Synth:
            def stream_chunks(self, text, **kwargs):
                yield b"synthetic-wave"
        speech_server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), Synth())
        speech_thread = threading.Thread(target=speech_server.serve_forever, daemon=True)
        speech_thread.start()
        speech_origin = f"http://127.0.0.1:{speech_server.server_address[1]}"
        script = r'''
import importlib.util, json, os, sys, threading, types
from urllib.request import build_opener, ProxyHandler, Request
sys.path.insert(0, sys.argv[1])
os.environ['LONGMEMORY_RUNTIME_URL'] = sys.argv[2] + '/api/internal/memory/prepare'
os.environ['LONGMEMORY_RUNTIME_TOKEN'] = 'a' * 64
import voice_diagnostics as diagnostic
base = types.ModuleType('core.providers.memory.base')
base.MemoryProviderBase = object
base.logger = None
sys.modules[base.__name__] = base
spec = importlib.util.spec_from_file_location('synthetic_memory_provider', sys.argv[1] + '/longmemory_provider.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
provider = object.__new__(module.MemoryProvider)
provider._lock = threading.Lock()
trace = diagnostic.VoiceRound()
token = diagnostic.CURRENT.set(trace)
try:
    trace.event('chat_entered')
    trace.event('memory_requested')
    result = provider._runtime_request('private synthetic transcript')
    assert result['context'] == 'private synthetic context'
    trace.event('tts_requested')
    request = Request(sys.argv[3] + '/v1/audio/stream',
        data=json.dumps({'input': 'private synthetic speech', 'stream': True}).encode(),
        headers={'Content-Type': 'application/json', 'X-Request-Id': 'forged-secret', **trace.headers()})
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        assert response.read(1024)
        speech_id = response.headers['X-Request-Id']
        assert speech_id != 'forged-secret'
        trace.event('tts_response', request_id=speech_id)
    trace.event('chat_returned')
finally:
    diagnostic.CURRENT.reset(token)
diagnostic._queue.join()
print(json.dumps({'round_id': trace.round_id, 'speech_id': speech_id}))
'''
        try:
            async with aiohttp.ClientSession(trust_env=False) as client:
                payload = {"round_id": "b" * 24, "sequence": 1, "event": "chat_entered"}
                response = await client.post(origin + "/api/internal/memory/voice-events", json=payload)
                assert response.status == 401 and observer.voice_snapshot()["rounds"] == []
                headers = {"Authorization": "Bearer " + "a" * 64, "X-Request-Id": "forged-private-id"}
                response = await client.post(origin + "/api/internal/memory/voice-events",
                                             json={**payload, "transcript": "private secret"}, headers=headers)
                assert response.status == 400
                response = await client.post(origin + "/api/internal/memory/voice-events",
                                             json=payload, headers=headers)
                assert response.status == 202 and response.headers["X-Request-Id"] != "forged-private-id"
            result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", script, str(source), origin, speech_origin],
                cwd=source.parents[2], capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, result.stderr
            round_id = json.loads(result.stdout)["round_id"]
            speech_id = json.loads(result.stdout)["speech_id"]
            await asyncio.to_thread(service._voice_observation._queue.join)
            row = next(row for row in observer.snapshot()["requests"] if row.get("voice_round_id") == round_id)
            assert row["stage"] == "context" and row["outcome"] == "accepted"
            rounds = {row["round_id"]: row for row in observer.voice_snapshot()["rounds"]}
            memory_event = next(event for event in rounds[round_id]["events"] if event["event"] == "memory_response")
            assert memory_event["http_request_id"] == row["request_id"]
            service_event = next(event for event in rounds[round_id]["events"] if event["event"] == "tts_service_returned")
            assert service_event["http_request_id"] == speech_id and service_event["source"] == "cosyvoice"
            assert "send_returned" in rounds[round_id]["missing"]
            assert rounds[round_id]["device_playback"] == "unconfirmed"
            audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            assert audit_rows[0]["voice_round_id"] == round_id
            assert audit_rows[0]["request_id"] == row["request_id"]
            assert "private" not in json.dumps(observer.snapshot())
            for path in (tmp_path / "data/logs/diagnostics").glob("*.jsonl*"):
                assert "private" not in path.read_text(encoding="utf-8")
        finally:
            await asyncio.to_thread(speech_server.shutdown)
            speech_server.server_close()
            speech_thread.join(timeout=3)
            close_file_logging(audit)
            await runner.cleanup()
    asyncio.run(run())


def test_untrusted_round_header_on_console_request_is_not_used():
    async def run():
        observer = Diagnostics()
        class Request(dict):
            path = "/api/device/status"
            method = "GET"
            headers = {"X-Voice-Round-Id": "a" * 24, "X-Request-Id": "b" * 24}
        async def handle(_request):
            return web.json_response({"ok": True})
        response = await observability_middleware(observer)(Request(), handle)
        row = observer.snapshot()["requests"][0]
        assert "voice_round_id" not in row and response.headers["X-Request-Id"] != "b" * 24
    asyncio.run(run())
