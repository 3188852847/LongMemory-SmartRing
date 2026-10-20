"""真实Runtime/HTTP/会话门＋进程内引擎替身；不读取个人库、不懒启动模型。"""

import asyncio
from datetime import UTC, datetime
from copy import deepcopy
import socket
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.application.semantic_tasks import validate_semantic_request
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.backend_contracts import ManagementCapabilities
from longmemory.methods.contracts import MethodCapabilities, UnsupportedCapabilityError, MemoryEvent, MemorySupport, RetrievedTrace
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.semantic import SemanticBusy
from longmemory.methods.hy_memory.layer_data import HyLayerDataBusy


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


@pytest.mark.parametrize("task_id", ["add:"+"a"*64+":expiry", "management:已核对%来源", "合成 任务", "😀"*256])
def test_native_task_ids_keep_colons_unicode_percent_and_python_length(task_id):
    validate_semantic_request("semantic_task", {"task_id": task_id})


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


def test_host_candidate_snapshot_uses_cpu_embedding_and_never_formal_prepare(tmp_path):
    runtime, method, _ = make_runtime(tmp_path)
    calls = []
    def embedding(body, role):
        calls.append(("embedding", body, role))
        return {"data": [{"embedding": [.25, .75]}]}
    method.candidate_snapshot = lambda **kwargs: (calls.append(("snapshot", kwargs)) or {
        "protocol": 1, "snapshot_token": "synthetic-token", "memory_digest": "synthetic-digest"})
    method.candidate_validate = lambda **kwargs: (calls.append(("validate", kwargs)) or True)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("candidate must not call side-effecting paths")
    for name in ("prepare_user", "prepare_round_screen", "status"):
        setattr(runtime, name, forbidden)
    for name in ("archive", "observe", "recall"):
        setattr(method, name, forbidden)
    runtime._model_service = SimpleNamespace(gateway=SimpleNamespace(
        encoder=SimpleNamespace(identity="synthetic-encoder"), embed=embedding), close=lambda: None)
    try:
        receipt = runtime.candidate_memory_snapshot("合成候选问题", limit=3)
        assert calls[:2] == [("embedding", {"model": "synthetic-encoder", "input": ["合成候选问题"]}, "query"),
                              ("snapshot", {"query_embedding": [.25, .75], "limit": 3})]
        assert runtime.validate_candidate_memory(snapshot_token="synthetic-token", memory_digest="synthetic-digest",
                                                  runtime_revision=receipt["runtime_revision"]) is True
        assert calls[-1] == ("validate", {"snapshot_token": "synthetic-token", "memory_digest": "synthetic-digest"})
        # 配置变化必须使旧Runtime票据无效，不把陈旧上下文重新包装成fresh。
        runtime.status = lambda: {}
        runtime.configure(write_enabled=False, use_enabled=True)
        before = len(calls)
        assert runtime.validate_candidate_memory(snapshot_token="synthetic-token", memory_digest="synthetic-digest",
                                                  runtime_revision=receipt["runtime_revision"]) is False
        assert len(calls) == before
        assert not runtime.database.exists()  # 本组合没有建库、来源或pending账本。
    finally:
        runtime.close()


def test_runtime_restart_and_disabled_use_invalidate_proposal_receipts(tmp_path):
    one, _, _ = make_runtime(tmp_path / "one")
    two, _, _ = make_runtime(tmp_path / "two")
    try:
        assert one._candidate_runtime_revision() != two._candidate_runtime_revision()
        one.configure(write_enabled=True, use_enabled=False)
        with pytest.raises(RuntimeError, match="candidate_memory_unavailable"):
            one.candidate_memory_snapshot("合成问题")
    finally:
        one.close()
        two.close()


def prepared_proposal(tmp_path):
    runtime, method, _ = make_runtime(tmp_path)
    event_id = str(uuid4())
    query, content = "合成问题", "合成用户喜欢整理资料。"
    source_ids = ["synthetic-source"]
    engine = {"protocol": 1, "read_status": "readable", "snapshot_token": "synthetic-token",
              "memory_digest": "synthetic-digest", "items": [{"memory_id": "fact1", "content": content,
                                                                "source_event_ids": source_ids}]}
    method.candidate_snapshot = lambda **_kwargs: deepcopy(engine)
    method.candidate_validate = lambda **_kwargs: {"protocol": 1, "valid": True, "memory_digest": "synthetic-digest"}
    runtime._model_service = SimpleNamespace(gateway=SimpleNamespace(encoder=SimpleNamespace(identity="synthetic"),
        embed=lambda *_args: {"data": [{"embedding": [.25, .75]}]}), close=lambda: None,
        status=lambda: {"state": "available"})
    receipt = runtime.candidate_memory_snapshot(query)
    prepared = SimpleNamespace(event=MemoryEvent(event_id, "user", query, datetime.now(UTC)),
        support=MemorySupport("call", content, (RetrievedTrace("fact1", content, tuple(source_ids)),)),
        memory_command=None, follow_up_suggestion=None)
    runtime.prepare_user = lambda *_args, **_kwargs: prepared
    runtime._round_screen_store = SimpleNamespace(expire=lambda: [], reserve=lambda **_kwargs: event_id,
        prepared=lambda *_args: None, feedback=lambda *_args: None)
    runtime.prepare_round_screen(query, client_round_id="b"*32, session_id="a"*32)
    arguments = dict(query=query, formal_turn_id=event_id, client_round_id="b"*32, session_id="a"*32)
    return runtime, receipt, arguments


def test_actual_formal_prepare_receipt_allows_one_locked_claim_with_nonempty_memory(tmp_path):
    runtime, receipt, arguments = prepared_proposal(tmp_path)
    claimed = []
    def claim():
        assert runtime._lock._is_owned()
        claimed.append(True)
        return "合成回答"
    try:
        assert runtime.claim_candidate_memory(receipt, **arguments, claim=claim) == "合成回答"
        assert runtime.claim_candidate_memory(receipt, **arguments, claim=claim) is None
        assert claimed == [True]
    finally:
        runtime.close()


@pytest.mark.parametrize("change", ["query", "session", "round", "formal_id", "content", "source", "settings", "engine", "management_uncertain"])
def test_formal_claim_rejects_cross_scope_stale_settings_or_changed_content_and_sources(tmp_path, change):
    runtime, receipt, arguments = prepared_proposal(tmp_path)
    try:
        if change == "query": arguments["query"] += "还有改口"
        elif change == "session": arguments["session_id"] = "c"*32
        elif change == "round": arguments["client_round_id"] = "c"*32
        elif change == "formal_id": arguments["formal_turn_id"] = str(uuid4())
        elif change == "content": receipt["engine"]["items"][0]["content"] = "另一项事实"
        elif change == "source": receipt["engine"]["items"][0]["source_event_ids"] = ["foreign-source"]
        elif change == "settings": runtime.configure(write_enabled=False, use_enabled=True)
        elif change == "engine": runtime._method.candidate_validate = lambda **_kwargs: {"protocol": 1, "valid": False}
        elif change == "management_uncertain":
            request_id = str(uuid4())
            source = MemoryEvent("hy-management:"+request_id,"user","合成更正",datetime.now(UTC),"a"*32)
            def missing(_event): raise LookupError
            runtime._method.source_detail = missing
            runtime._method.archive = lambda _source: None
            runtime.backend_assembly.management.failure = RuntimeError("hy_management_outcome_uncertain")
            with pytest.raises(RuntimeError, match="outcome_uncertain"):
                runtime.administer_extension("hy_memory","correct",request_id=request_id,item_id="synthetic",
                    expected_revision="synthetic",content=source.content,source=source)
        assert runtime.claim_candidate_memory(receipt, **arguments,
            claim=lambda: (_ for _ in ()).throw(AssertionError("invalid claim called"))) is None
    finally:
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
                for identifier in ("add:"+"a"*64+":expiry", "management:合成%任务"):
                    from urllib.parse import quote
                    async with client.get(path + "/tasks/" + quote(identifier, safe="")) as response:
                        assert response.status == 200 and (await response.json())["task_id"] == identifier
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
                admin.failure = HyResponseError("hy_worker_operation_failed_LookupError_state_unknown")
                async with client.get(path + "/tasks/t1") as response:
                    assert response.status == 404
                for failure, expected in ((RuntimeError("hy_semantic_busy"), 503),
                                          (SemanticBusy("hy_semantic_status_busy"), 503),
                                          (HyLayerDataBusy("hy_layer_data_busy"), 503),
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
