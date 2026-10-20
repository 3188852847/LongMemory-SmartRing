"""真实Runtime/HTTP/会话门＋进程内引擎替身；不读取个人库、不懒启动模型。"""

import asyncio
from datetime import datetime
import socket
from threading import Event, Thread
from types import SimpleNamespace

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.semantic_tasks import validate_semantic_request
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.backend_contracts import ManagementCapabilities
from longmemory.methods.contracts import MethodCapabilities, UnsupportedCapabilityError


def make_runtime(tmp_path):
    class Method:
        name, implementation_version = "hy_memory", "synthetic"
        capabilities = MethodCapabilities()
        def __init__(self):
            self.calls, self.failure = [], False
        def configure_background_writes(self, *, write_enabled):
            self.calls.append(write_enabled)
            if self.failure:
                raise RuntimeError("PRIVATE ENGINE FAILURE")
        def wait_until_ready(self):
            pass
        def close(self):
            pass

    class Administration:
        extension_namespace = "hy_memory"
        capabilities = ManagementCapabilities()
        def __init__(self):
            self.calls, self.failure = [], None
        def extension(self, operation, **arguments):
            self.calls.append((operation, arguments))
            if self.failure:
                raise self.failure
            if operation == "semantic_status":
                return {"protocol": 2, "enabled": False, "desired_enabled": False, "mode": "pro",
                        "graph_available": False, "schema_state": "disabled", "task_counts": {},
                        "paused": True, "management_available": False, "last_task_finished_at": None,
                        "epoch": None, "ready_epoch": None, "native_evolve_idempotent": False,
                        "automatic_restart_replay": False, "intention_read": "disabled",
                        "expired_intention_policy": "disabled", "execution_authorized": False,
                        "proactive_contact_enabled": False}
            if arguments.get("task_id") == "missing":
                raise LookupError("private")
            return {"task_id": arguments["task_id"], "kind": "evolve", "state": "pending",
                    "created_at": "2026-10-21T00:00:00+00:00", "finished_at": None,
                    "elapsed_ms": None, "reason_code": None}
    method, admin = Method(), Administration()
    assembly = SimpleNamespace(legacy_sqlite=False, management=admin, resources=[])
    runtime = MemoryRuntime(tmp_path / "synthetic-unused.sqlite3", method=method, backend_assembly=assembly)
    return runtime, method, admin


def test_initialization_and_changes_sync_actual_method_gate_and_failure_pauses(tmp_path):
    runtime, method, _ = make_runtime(tmp_path)
    try:
        assert method.calls == [True]
        runtime.configure(write_enabled=False, use_enabled=True)
        runtime.configure(write_enabled=False, use_enabled=False)
        assert method.calls == [True, False]
        runtime.configure(write_enabled=True, use_enabled=False)
        assert method.calls == [True, False, True]
        method.failure = True
        with pytest.raises(RuntimeError, match="^memory_background_write_gate_failed$"):
            runtime.configure(write_enabled=False, use_enabled=True)
        assert not runtime._write_enabled
        assert runtime._use_enabled is False  # 未成功的其他配置不先行生效。
    finally:
        runtime.close()


def test_enqueue_uses_write_gate_cancel_does_not_and_read_never_calls_status(tmp_path):
    runtime, _, admin = make_runtime(tmp_path)
    try:
        runtime.configure(write_enabled=False, use_enabled=True)
        runtime.status = lambda: (_ for _ in ()).throw(AssertionError("read must not expire ledger"))
        with pytest.raises(ValueError, match="memory_write_paused"):
            runtime.administer_extension("hy_memory", "semantic_enqueue", task_id="t1", kind="evolve", max_batches=1)
        assert not admin.calls
        status = runtime.administer_extension("hy_memory", "semantic_status")
        assert status["runtime"] == {"write_enabled": False, "use_enabled": True}
        assert not status["execution_authorized"] and not status["proactive_contact_enabled"]
        result = runtime.administer_extension("hy_memory", "semantic_cancel", task_id="t1")
        assert result["task_id"] == "t1"
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer_extension("hy_memory", "semantic_pause", paused=False)
    finally:
        runtime.close()


@pytest.mark.parametrize("operation,args", [
    ("semantic_pause", {"paused": False}), ("semantic_status", {"extra": "value"}),
    ("semantic_task", {"task_id": "../private"}),
    ("semantic_enqueue", {"task_id": "t1", "kind": "execute", "max_batches": 1}),
    ("semantic_enqueue", {"task_id": "t1", "kind": "evolve", "max_batches": True}),
    ("semantic_enqueue", {"task_id": "t1", "kind": "evolve", "max_batches": 5}),
    ("semantic_enqueue", {"task_id": "t1", "kind": [], "max_batches": 1}),
])
def test_platform_schema_is_a_fixed_bounded_whitelist(operation, args):
    with pytest.raises(ValueError, match="hy_semantic_request_invalid"):
        validate_semantic_request(operation, args)


def test_read_lock_is_nonblocking_and_queues_no_sdk_work(tmp_path):
    runtime, _, admin = make_runtime(tmp_path)
    entered, release = Event(), Event()
    def hold():
        with runtime._lock:
            entered.set()
            assert release.wait(3)
    thread = Thread(target=hold)
    thread.start()
    try:
        assert entered.wait(2)
        for operation, args in (("semantic_status", {}), ("semantic_task", {"task_id": "t1"})):
            with pytest.raises(RuntimeError, match="hy_semantic_busy"):
                runtime.administer_extension("hy_memory", operation, **args)
        assert not admin.calls
    finally:
        release.set()
        thread.join(2)
        runtime.close()


def test_http_shapes_read_peek_auth_write_gates_and_errors(tmp_path):
    runtime, _, admin = make_runtime(tmp_path)
    async def run():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sessions = Sessions()
        session, csrf = sessions.create()
        app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])
        peek = [runtime]
        def forbidden_lazy():
            raise AssertionError("semantic API must not initialize runtime")
        register_memory_engine_routes(app, forbidden_lazy, allow_correction=True, snapshot_runtime=lambda: peek[0])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        base = f"http://127.0.0.1:{port}"
        path = base + "/api/memory-engine/hy/semantic"
        headers = {"Origin": base, "X-Console-CSRF": csrf}
        try:
            async with ClientSession(cookie_jar=CookieJar(unsafe=True), cookies={"lm_console_session": session}) as client:
                async with client.get(path + "/status") as response:
                    assert response.status == 200
                    body = await response.json()
                    assert body["protocol"] == 2 and body["enabled"] is False
                    assert "status" not in body and "data" not in body
                    assert body["runtime"] == {"write_enabled": True, "use_enabled": True}
                    assert datetime.fromisoformat(body["observed_at"]).tzinfo is not None
                async with client.get(path + "/tasks/t1") as response:
                    assert response.status == 200 and (await response.json())["task_id"] == "t1"
                async with client.get(path + "/tasks/missing") as response:
                    assert response.status == 404
                for url in (path + "/status?extra=1", path + "/tasks/t1?x=1"):
                    async with client.get(url) as response:
                        assert response.status == 400
                async with client.post(path + "/tasks", json={"task_id": "t1", "kind": "evolve", "max_batches": 1}) as response:
                    assert response.status == 403  # 真实中间件CSRF门。
                runtime.configure(write_enabled=False, use_enabled=True)
                async with client.post(path + "/tasks", headers=headers, json={"task_id": "t1", "kind": "evolve", "max_batches": 1}) as response:
                    assert response.status == 403 and (await response.json())["error"] == "memory_write_paused"
                async with client.post(path + "/tasks/t1/cancel", headers=headers, json={}) as response:
                    assert response.status == 200
                for body in ({"task_id": "t1", "kind": "evolve", "max_batches": True},
                             {"task_id": "t1", "kind": "evolve", "max_batches": 1, "source": "forbidden"}):
                    async with client.post(path + "/tasks", headers=headers, json=body) as response:
                        assert response.status == 400
                for failure, expected in ((RuntimeError("hy_semantic_busy"), 503),
                                          (RuntimeError("PRIVATE"), 503), (UnsupportedCapabilityError(), 501)):
                    admin.failure = failure
                    async with client.get(path + "/status") as response:
                        assert response.status == expected and "PRIVATE" not in await response.text()
                admin.failure = None
                peek[0] = None
                async with client.get(path + "/status") as response:
                    assert response.status == 503 and (await response.json())["error"] == "hy_semantic_unavailable"
        finally:
            await runner.cleanup()
    try:
        asyncio.run(run())
    finally:
        runtime.close()
