"""只读分页/HTTP边界与锁；真实SDK覆盖见integration/test_hy_layer_data_sdk.py。"""

import asyncio
from copy import deepcopy
import hashlib
import json
import socket
import sys
from threading import Event, Thread, RLock
from types import SimpleNamespace, ModuleType

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.bootstrap import assemble_backend, build_backend_runtime
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.backend_contracts import StateResource
from longmemory.methods.hy_memory.assembly import assemble_hy_backend
from longmemory.methods.hy_memory.layer_data import LayerDataRPC, LAYERS, HyLayerDataBusy, _record
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.worker import RequestBudget
from longmemory.methods.hy_memory.method import HyMemoryMethod, HyAdministration
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError, SOURCE_NAMESPACE
from longmemory.methods.hy_memory.settings import HySettings


def forbidden(*args, **kwargs):
    pytest.fail("逐层读取不得启动SDK/调用模型、search、profile、status或旧list")


def payload(name="native", *, layer=LAYERS[2], **values):
    return {"node_id": name, "user_id": "synthetic-user", "agent_id": "synthetic-agent", "source": SOURCE_NAMESPACE,
        "layer": layer, "content": "真实类型合成内容", "status": "active", "is_latest": True,
        "supersedes": "", "superseded_by": "", "custom": {}, **values}


def response(layer=LAYERS[2], **kwargs):
    return {**LayerDataRPC(None, None, None)._base(layer), "data_state": "present",
        "items": [_record(payload(layer=layer))], "limit": 20, "offset": 0, "state": "all",
        "total": 1, "has_more": False, "count_scope": "owner_agent_source_layer_state_vdb", **kwargs}


def make_runtime(root):
    method = HyMemoryMethod(settings=HySettings(user_id="synthetic-user", agent_id="synthetic-agent"), client_factory=forbidden)
    calls = []
    def page(**args):
        calls.append(args)
        return response(args["layer"], limit=args["limit"], offset=args["offset"], state=args["state"])
    method._client = SimpleNamespace(layer_page=page,
        layer_detail=lambda **args: None if args["item_id"] == "missing" else {
            **LayerDataRPC(None, None, None)._base(args["layer"]), "data_state": "present",
            "item": _record(payload(args["item_id"], layer=args["layer"]), detail=True), "versions": None})
    assembly = assemble_backend(method=method, source_path=root / "sources.db", create_sources=True,
        resources=(StateResource("s", root / "engine", "directory"),), management=HyAdministration(method))
    return build_backend_runtime(assembly), method, calls


async def request(runtime, path, *, authenticated=True, body=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8767, 8768, 8000, 8003, 18000, 18003, 18770}
    base = f"http://127.0.0.1:{port}"
    sessions = Sessions()
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])
    async def session(_):
        identity, _ = sessions.create()
        result = web.json_response({"ok": True})
        result.set_cookie("lm_console_session", identity, httponly=True)
        return result
    app.router.add_get("/api/session", session)
    register_memory_engine_routes(app, runtime)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.SockSite(runner, sock).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            if authenticated:
                assert (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).status == 200
            result = await client.get(base + "/api/memory-engine/hy/layers/" + path, data=body)
            return result.status, await result.text()
    finally:
        await runner.cleanup()
        sock.close()


def digest(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file() and p.suffix != ".owner"}


def test_http_auth_read_paused_missing_and_no_writes_or_status(tmp_path):
    runtime, method, calls = make_runtime(tmp_path)
    try:
        runtime.configure(write_enabled=False, use_enabled=False)
        runtime.status = forbidden
        before = digest(tmp_path)
        assert asyncio.run(request(runtime, LAYERS[2], authenticated=False))[0] == 401
        status, body = asyncio.run(request(runtime, LAYERS[2] + "?limit=2&offset=1&state=superseded"))
        assert status == 200 and json.loads(body)["items"][0]["content"] == "真实类型合成内容"
        assert calls == [{"layer": LAYERS[2], "limit": 2, "offset": 1, "state": "superseded"}]
        assert asyncio.run(request(runtime, LAYERS[2] + "/items/native"))[0] == 200
        assert asyncio.run(request(runtime, LAYERS[2] + "/items/missing"))[0] == 404
        assert digest(tmp_path) == before
        assert not (tmp_path / "engine/management.sqlite3").exists()
        method._closed = True
        assert asyncio.run(request(runtime, LAYERS[2]))[0] == 503
        method._closed = False
    finally:
        runtime.close()
    assert asyncio.run(request(runtime, LAYERS[2]))[0] == 503


@pytest.mark.parametrize("path", ["invalid", "l2_FACT", "l2_fact?limit=0", "l2_fact?limit=51", "l2_fact?offset=-1",
    "l2_fact?offset=10001", "l2_fact?state=unknown", "l2_fact?limit=2&limit=3", "l2_fact?user_id=foreign",
    "l0_basic_info?state=active", "l2_fact/items/id?path=secret", "l2_fact/items/%00"])
def test_http_invalid_layer_page_and_id_never_call_sdk(tmp_path, path):
    runtime, _, calls = make_runtime(tmp_path)
    try:
        assert asyncio.run(request(runtime, path))[0] == 400
        assert calls == []
    finally:
        runtime.close()


def test_http_get_body_refused_and_legacy_missing_error_are_safe(tmp_path):
    runtime, method, _ = make_runtime(tmp_path)
    try:
        assert asyncio.run(request(runtime, LAYERS[2], body="private"))[0] == 400
        assert asyncio.run(request(None, LAYERS[2]))[0] == 503
        assert asyncio.run(request(SimpleNamespace(), LAYERS[2]))[0] == 501
        method._client.layer_page = lambda **args: (_ for _ in ()).throw(HyResponseError("PRIVATE_KEY_AND_PATH"))
        status, text = asyncio.run(request(runtime, LAYERS[2]))
        assert status == 503 and "PRIVATE" not in text
        method._client.layer_page = lambda **args: response(**{"private_path": "PRIVATE_KEY"})
        status, text = asyncio.run(request(runtime, LAYERS[2]))
        assert status == 503 and "PRIVATE" not in text
    finally:
        runtime.close()


@pytest.mark.parametrize("which", ["runtime", "method"])
def test_busy_locks_do_not_queue_or_delay_chat(tmp_path, which):
    runtime, method, calls = make_runtime(tmp_path)
    lock = runtime._lock if which == "runtime" else method._lock
    held, release = Event(), Event()
    def hold():
        with lock:
            held.set()
            assert release.wait(10)
    thread = Thread(target=hold)
    thread.start()
    try:
        assert held.wait(2)
        status, text = asyncio.run(request(runtime, LAYERS[1]))
        assert status == 503 and "hy_layer_data_busy" in text
        assert calls == [] and not release.is_set()
    finally:
        release.set()
        thread.join(2)
        runtime.close()


def test_native_chroma_filters_limit_lookahead_offset_include_and_count_scope(tmp_path, monkeypatch):
    monkeypatch.setattr("longmemory.methods.hy_memory.management_rpc.owner_lease_held", lambda workspace: True)
    records = [payload(str(n), status="superseded" if n == 1 else "active") for n in range(4)]
    records += [payload("foreign", agent_id="other-agent", content="PRIVATE_FOREIGN")]
    calls = []
    def get(**args):
        calls.append(args)
        selected = [r for r in records if all(r.get(k) == v["$eq"] for condition in args["where"]["$and"] for k, v in condition.items())]
        if "ids" in args:
            selected = [r for r in selected if r["node_id"] in args["ids"]]
        selected = selected[args["offset"]:args["offset"] + args["limit"]]
        return {"ids": [r["node_id"] for r in selected], "metadatas": deepcopy(selected)}
    store = type("ChromaVectorStore", (), {})()
    store._collection = SimpleNamespace(get=get)
    store._node_id_to_point_id = lambda name: name
    store._chroma_metadata_to_payload = lambda meta: meta
    async def pool(function, **args):
        return function(**args)
    module = ModuleType("hy_memory.data.vector_store_chroma")
    module._run_in_vdb_pool = pool
    monkeypatch.setitem(sys.modules, "hy_memory.data.vector_store_chroma", module)
    config = SimpleNamespace(vector_store=SimpleNamespace(host=None), enable_graph=False,
        graph_store=SimpleNamespace(provider="kuzu", db_path=str(tmp_path / "sdk/graph")))
    client = SimpleNamespace(_vector_store=store, _config=config, _graph_store=None, _loop_thread=SimpleNamespace(run=asyncio.run))
    reader = LayerDataRPC(client, HySettings(user_id="synthetic-user", agent_id="synthetic-agent"),
        SimpleNamespace(actual_sdk_version="2.0.3", management_workspace=tmp_path))
    page = reader.execute("layer_page", {"layer": LAYERS[2], "state": "all", "limit": 2, "offset": 0})
    assert page["total"] is None and page["has_more"] and len(page["items"]) == 2
    assert calls[-1]["limit"] == 3 and calls[-1]["offset"] == 0 and calls[-1]["include"] == ["metadatas"]
    assert "PRIVATE" not in str(page)
    last = reader.execute("layer_page", {"layer": LAYERS[2], "state": "all", "limit": 2, "offset": 2})
    assert last["total"] == 4 and last["has_more"] is False
    missing = reader.execute("layer_page", {"layer": LAYERS[2], "state": "all", "limit": 2, "offset": 99})
    assert missing["total"] is None and missing["data_state"] == "unknown"
    assert reader.execute("layer_detail", {"layer": LAYERS[2], "item_id": "foreign"}) is None
    for layer in (LAYERS[4], LAYERS[5]):
        empty = reader.execute("layer_page", {"layer": layer, "state": "all", "limit": 2, "offset": 0})
        assert empty["total"] == 0 and empty["data_state"] == "empty"
    graph_path = tmp_path / "sdk/graph"
    graph_path.parent.mkdir()
    graph_path.write_bytes(b"synthetic-existing-marker")
    graph = reader.execute("layer_page", {"layer": LAYERS[6], "state": "all", "limit": 2, "offset": 0})
    assert graph["read_status"] == "partial" and graph["data_state"] == "unknown" and graph["total"] is None
    records[0]["custom"] = {"meta": [{"namespace": "foreign", "source_event_ids": ["PRIVATE_FOREIGN"]}]}
    with pytest.raises(HyResponseError, match="scope_mismatch"):
        reader.execute("layer_page", {"layer": LAYERS[2], "state": "all", "limit": 2, "offset": 0})
    monkeypatch.setattr("longmemory.methods.hy_memory.management_rpc.owner_lease_held", lambda workspace: False)
    calls_before = len(calls)
    denied = reader.execute("layer_page", {"layer": LAYERS[2], "state": "all", "limit": 2, "offset": 0})
    assert denied["read_status"] == "unavailable" and denied["total"] is None
    assert len(calls) == calls_before


def test_old_proof_is_refused_before_any_factory_or_state_creation(tmp_path):
    with pytest.raises(ValueError, match="verification_identity_mismatch"):
        assemble_hy_backend(settings=HySettings(user_id="synthetic"), state_directory=tmp_path / "engine",
            source_path=tmp_path / "sources.db", create=True, client_factory=forbidden,
            management_verification={"sdk_version": "2.0.3", "rpc_source_sha256": "e358debcfa870e09c6072645758d70ac4fa6792bcfb1dd5d589f3c1490657e04",
                "real_sdk_rpc_verified": True, "semantic_background_writes_disabled": True})
    assert not (tmp_path / "engine").exists() and not (tmp_path / "sources.db").exists()


def test_rpc_layer_lock_is_nonblocking_and_read_operation_denies_model_transport():
    client = HyProcessClient.__new__(HyProcessClient)
    client._lock = RLock()
    held, release = Event(), Event()
    def hold():
        with client._lock:
            held.set()
            assert release.wait(10)
    thread = Thread(target=hold)
    thread.start()
    try:
        assert held.wait(2)
        with pytest.raises(HyLayerDataBusy):
            client.layer_page(layer=LAYERS[1])
        assert not release.is_set()
    finally:
        release.set()
        thread.join(2)
    budget = RequestBudget(HySettings(user_id="synthetic"))
    for operation in ("layer_page", "layer_detail"):
        budget.operation = operation
        with pytest.raises(RuntimeError, match="model_denied"):
            budget.check_management_request("https://blocked.invalid/v1/embeddings")
    assert budget.attempts == budget.simulated_requests == 0


def test_read_rpc_response_timeout_is_bounded_and_never_retried():
    import queue
    client = HyProcessClient.__new__(HyProcessClient)
    client._lock, client._closed, client._counter = RLock(), False, 0
    writes, timeouts, stopped = [], [], []
    def receive(*, timeout):
        timeouts.append(timeout)
        raise queue.Empty()
    client._process = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, flush=lambda: None))
    client._responses = SimpleNamespace(get=receive)
    client._stop = lambda: stopped.append(True)
    with pytest.raises(HyResponseError, match="transport_failed"):
        client.layer_page(layer=LAYERS[1])
    assert timeouts == [5] and len(writes) == 1 and stopped == [True]
