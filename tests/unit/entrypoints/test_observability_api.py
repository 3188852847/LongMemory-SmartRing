"""临时端口上验证认证、离线、超时和故障信息白名单，不访问日用服务。"""

import asyncio
import json
import socket
from pathlib import Path
import subprocess
import sys

import aiohttp
from aiohttp import web
import pytest

from longmemory.adapters.device_control.protocol import BridgeError
from longmemory.entrypoints.api.server import create_app
from longmemory.infrastructure.logging.diagnostics import Diagnostics
from longmemory.infrastructure.logging.setup import log_event


class Bridge:
    async def status(self):
        raise BridgeError("bridge_unavailable", 503)

    async def set_volume(self, volume):
        raise BridgeError("bridge_timeout", 504)

    async def close(self):
        pass


def test_authenticated_summary_and_safe_failure_metadata(tmp_path):
    async def run():
        observer = Diagnostics(tmp_path)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app = create_app(port=port, bridge=Bridge(), diagnostics=observer, proactive_schedule_enabled=False)

        async def failed(_request):
            raise RuntimeError("synthetic-api-key and private conversation")

        async def memory(_request):
            await asyncio.to_thread(log_event, "context_built", turn_id="synthetic-turn", count=0)
            return web.json_response({"ok": True})

        async def timeout(_request):
            raise TimeoutError("synthetic-private-timeout")

        app.router.add_post("/api/synthetic-failed", failed)
        app.router.add_get("/api/synthetic-timeout", timeout)
        app.router.add_get("/api/synthetic-memory", memory)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        origin = f"http://127.0.0.1:{port}"
        try:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as client:
                response = await client.get(origin + "/api/observability")
                assert response.status == 401
                response = await client.get(origin + "/api/session", headers={"X-Console-Bootstrap": "1"})
                csrf = (await response.json())["csrf"]
                headers = {"Origin": origin, "X-Console-CSRF": csrf}
                response = await client.get(origin + "/api/device")
                offline_id = response.headers["X-Request-Id"]
                assert response.status == 503
                response = await client.post(origin + "/api/device/volume", json={"volume": 30}, headers=headers)
                timeout_id = response.headers["X-Request-Id"]
                assert response.status == 504
                response = await client.post(origin + "/api/synthetic-failed", headers=headers)
                failure_id = response.headers["X-Request-Id"]
                assert response.status == 500
                assert "private" not in await response.text()
                response = await client.get(origin + "/api/synthetic-timeout")
                assert response.status == 504
                response = await client.get(origin + "/api/synthetic-memory")
                memory_id = response.headers["X-Request-Id"]
                response = await client.get(origin + "/api/observability")
                snapshot = await response.json()
                rows = {row["request_id"]: row for row in snapshot["requests"]}
                assert rows[offline_id]["code"] == "bridge_unavailable"
                assert rows[offline_id]["outcome"] == "failed"
                assert rows[timeout_id]["code"] == "bridge_timeout"
                assert rows[timeout_id]["outcome"] == "unknown"
                assert rows[failure_id]["outcome"] == "unknown"
                assert rows[memory_id]["stage"] == "context"
                assert "private" not in json.dumps(snapshot)
                assert "synthetic-api-key" not in json.dumps(snapshot)
                assert snapshot["device_playback"] == "unconfirmed"
                for _ in range(3):
                    response = await client.get(origin + "/api/observability")
                    assert (await response.json())["requests"] == snapshot["requests"]
                response = await client.get(origin + "/api/observability", headers={"Origin": "https://outside.example"})
                assert response.status == 403
                response = await client.post(origin + "/api/observability", headers=headers)
                assert response.status == 405
        finally:
            await runner.cleanup()
    asyncio.run(run())


def test_separate_http_client_receives_id_linked_to_memory_stage(tmp_path):
    async def run():
        observer = Diagnostics(tmp_path)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app = create_app(port=port, bridge=Bridge(), diagnostics=observer,
                         memory_runtime_token="synthetic-internal-token", proactive_schedule_enabled=False)

        async def probe(_request):
            await asyncio.to_thread(log_event, "context_built", turn_id="synthetic-cross-process-turn", count=0)
            return web.json_response({"ok": True})

        app.router.add_post("/api/internal/memory/diagnostic-probe", probe)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, listener).start()
        script = """
import sys
from urllib.request import build_opener, ProxyHandler, Request
url = sys.argv[1]
request = Request(url, data=b'{}', headers={'Authorization': 'Bearer synthetic-internal-token',
                                         'X-Request-Id': 'untrusted-client-secret'})
with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
    print(response.headers['X-Request-Id'])
"""
        try:
            result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", script,
                f"http://127.0.0.1:{port}/api/internal/memory/diagnostic-probe"],
                cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            request_id = result.stdout.strip()
            row = observer.snapshot()["requests"][0]
            assert row["request_id"] == request_id
            assert row["operation"] == "memory_runtime" and row["stage"] == "context"
            assert row["stages"][0]["event"] == "context_built"
            assert "untrusted-client-secret" not in json.dumps(observer.snapshot())
        finally:
            await runner.cleanup()
    asyncio.run(run())


def test_cancellation_marks_write_result_unknown():
    from longmemory.entrypoints.api.observability import observability_middleware

    async def run():
        observer = Diagnostics()
        async def cancelled(_request):
            raise asyncio.CancelledError()
        class Request(dict):
            path = "/api/device/volume"
            method = "POST"
        with pytest.raises(asyncio.CancelledError):
            await observability_middleware(observer)(Request(), cancelled)
        row = observer.snapshot()["requests"][0]
        assert row["code"] == "response_unobserved" and row["outcome"] == "unknown"
    asyncio.run(run())
