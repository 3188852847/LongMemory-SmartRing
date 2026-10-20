"""机制观察必须无SDK/RPC/模型、无持久写，也不能把声明当现场健康。"""

import asyncio
import hashlib
import json
import socket
from types import SimpleNamespace
from threading import Event, Thread

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.bootstrap import assemble_backend, build_backend_runtime
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.backend_contracts import StateResource
from longmemory.methods.contracts import UnsupportedCapabilityError
from longmemory.methods.hy_memory.method import HyMemoryMethod, HyAdministration
from longmemory.methods.hy_memory.settings import Endpoint, HySettings


def make_method(*, standard=True, profile=True):
    def forbidden():
        pytest.fail("机制观察不得启动SDK或执行任何RPC")
    method = HyMemoryMethod(settings=HySettings(user_id="PRIVATE_USER", agent_id="PRIVATE_AGENT",
        llm=Endpoint(api_key="PRIVATE_KEY", model="PRIVATE_MODEL"), include_profile=profile), client_factory=forbidden)
    if standard:
        method._mechanism_profile = "standard_worker"
    return method


def by_id(rows):
    return {row["id"]: row for row in rows}


def test_standard_declarations_layers_channels_and_unknowns_do_not_start_sdk():
    method = make_method()
    result = HyAdministration(method).extension("mechanisms")
    assert method._client is None
    assert result["sdk"]["version"] == "2.0.3"
    assert result["mode"] == "pro" and result["scene"] == "chat"
    assert result["runtime"] == {"engine_initialized": False, "worker_health": "unknown"}
    assert [item["number"] for item in result["layers"]] == list(range(8))
    layers = by_id(result["layers"])
    assert layers["l0_basic_info"]["title"] == "基本信息"
    assert layers["l4_identity"]["integration"] == layers["l5_knowledge"]["integration"] == "reserved"
    assert layers["l6_schema"]["integration"] == layers["l7_intention"]["integration"] == "disabled"
    assert all(item["count"] is None for item in layers.values())
    mechanisms = by_id(result["mechanisms"])
    for name in ("system2", "sdk_history", "graph_store", "schema_recall", "proactive_recall", "intention_extraction"):
        assert mechanisms[name]["integration"] == "disabled"
    assert mechanisms["optional_recall_enhancements"]["integration"] == "unknown"
    assert mechanisms["working_route"]["integration"] == mechanisms["coding_route"]["integration"] == "not_integrated"
    assert mechanisms["answer_injection"]["integration"] == "configured"
    serialized = json.dumps(result)
    for private in ("PRIVATE_USER", "PRIVATE_AGENT", "PRIVATE_KEY", "PRIVATE_MODEL"):
        assert private not in serialized
    assert "path" not in result and result["evidence_gaps"]


def test_custom_factory_is_unknown_and_profile_setting_is_observed():
    method = make_method(standard=False, profile=False)
    result = HyAdministration(method).extension("mechanisms")
    assert result["assembly"] == "custom_or_unknown"
    assert result["mode"] is result["scene"] is None
    assert all(item["selected"] is None for item in result["modes"])
    mechanisms = by_id(result["mechanisms"])
    assert mechanisms["graph_store"]["integration"] == "unknown"
    assert mechanisms["profile_recall"]["integration"] == "disabled"
    assert all(item["integration"] in {"reserved", "unknown"} for item in result["layers"])
    with pytest.raises(ValueError, match="arguments_invalid"):
        HyAdministration(method).extension("mechanisms", path="private")


def make_runtime(root, *, admin=True):
    method = make_method()
    # Runtime装配需要ready；使用无行为client，后续每种RPC均会因缺少方法而失败。
    method._client = SimpleNamespace(close=lambda: None)
    assembly = assemble_backend(method=method, resources=(StateResource("synthetic", root / "engine", "directory"),),
        source_path=root / "sources.db", create_sources=True, management=HyAdministration(method) if admin else None)
    return build_backend_runtime(assembly)


def snapshot(root):
    # Windows生命周期租约文件被OS锁定，保持文件集合但不绕过锁读取其字节。
    return {str(path.relative_to(root)): None if path.suffix == ".owner" else hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_runtime_read_preserves_all_synthetic_state_and_current_gates(tmp_path):
    runtime = make_runtime(tmp_path)
    try:
        runtime.configure(write_enabled=False, use_enabled=False)
        # 若误调用status会执行expire；这个替身证明新端点不经过它。
        runtime._round_screen_store = SimpleNamespace(expire=lambda: pytest.fail("禁止账本过期写"))
        before = snapshot(tmp_path)
        for _ in range(2):
            result = runtime.administer_extension("hy_memory", "mechanisms")
            assert result["runtime"]["write_enabled"] is False
            assert result["runtime"]["use_enabled"] is False
            assert result["runtime"]["engine_initialized"] is True
        assert snapshot(tmp_path) == before
        assert not (tmp_path / "engine" / "management.sqlite3").exists()
    finally:
        runtime._round_screen_store = None
        runtime.close()
    with pytest.raises(RuntimeError):
        runtime.administer_extension("hy_memory", "mechanisms")


def test_runtime_without_hy_management_refuses(tmp_path):
    runtime = make_runtime(tmp_path, admin=False)
    try:
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer_extension("hy_memory", "mechanisms")
    finally:
        runtime.close()


async def http_read(runtime, *, query="", authenticated=True, body=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8767, 8768, 8000, 8003, 18000, 18003, 18770}
    base = f"http://127.0.0.1:{port}"
    sessions = Sessions()
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])
    async def session(request):
        identity, csrf = sessions.create()
        response = web.json_response({"csrf": csrf})
        response.set_cookie("lm_console_session", identity, httponly=True)
        return response
    app.router.add_get("/api/session", session)
    register_memory_engine_routes(app, runtime)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.SockSite(runner, sock).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            if authenticated:
                assert (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).status == 200
            response = await client.get(base + "/api/memory-engine/hy/mechanisms" + query, data=body)
            return response.status, await response.text()
    finally:
        await runner.cleanup()
        sock.close()


def test_http_auth_strict_query_disabled_and_no_status_call(tmp_path):
    runtime = make_runtime(tmp_path)
    try:
        runtime.configure(write_enabled=False, use_enabled=False)
        runtime.status = lambda: pytest.fail("status会写账本")
        assert asyncio.run(http_read(runtime, authenticated=False))[0] == 401
        assert asyncio.run(http_read(runtime, query="?path=private"))[0] == 400
        assert asyncio.run(http_read(runtime, body="private"))[0] == 400
        status, body = asyncio.run(http_read(runtime))
        assert status == 200
        assert json.loads(body)["runtime"]["use_enabled"] is False
        assert "PRIVATE_" not in body
    finally:
        runtime.close()


@pytest.mark.parametrize("kind, expected, error", [
    ("unconfigured", 503, "memory_runtime_unavailable"),
    ("old", 501, "memory_backend_capability_unsupported"),
    ("failed", 503, "hy_mechanisms_unavailable"),
])
def test_http_missing_legacy_and_safe_errors(kind, expected, error):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_STACK_OR_KEY")
    runtime = None if kind == "unconfigured" else SimpleNamespace(
        **({"administer_extension": fail} if kind == "failed" else {}))
    status, body = asyncio.run(http_read(runtime))
    assert status == expected and json.loads(body)["error"] == error
    assert "PRIVATE" not in body


@pytest.mark.parametrize("which", ["runtime", "engine"])
def test_busy_chat_or_management_lock_returns_immediately_without_queueing(tmp_path, which):
    runtime = make_runtime(tmp_path)
    lock = runtime._lock if which == "runtime" else runtime.backend_assembly.management.method._lock
    acquired, release = Event(), Event()
    def hold():
        with lock:
            acquired.set()
            assert release.wait(10)
    worker = Thread(target=hold)
    worker.start()
    try:
        assert acquired.wait(2)
        # 若排队等待锁，HTTP检查将直到上述10秒超时才结束并失败。
        status, body = asyncio.run(http_read(runtime))
        assert not release.is_set()
        assert status == 503 and json.loads(body)["error"] == "hy_mechanisms_busy"
    finally:
        release.set()
        worker.join(2)
        runtime.close()


def test_closing_runtime_does_not_return_live_snapshot(tmp_path):
    runtime = make_runtime(tmp_path)
    try:
        runtime._closing = True
        assert asyncio.run(http_read(runtime))[0] == 503
    finally:
        runtime._closing = False
        runtime.close()
