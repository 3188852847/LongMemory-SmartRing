"""正式create_app只窥视已装配身份；不得懒建库、调SDK或等聊天锁。"""

import asyncio
from contextlib import asynccontextmanager
import socket
import sqlite3
from threading import Event, Thread
from types import SimpleNamespace

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.entrypoints.api import server
from longmemory.entrypoints.api.chat_backend import ChatBackend


def forbidden(*args, **kwargs):
    pytest.fail("身份读取不能初始化、读库、SDK或调用status")


def runtime(root):
    engine = SimpleNamespace(name="hy_memory_pro_chat",
        wait_until_ready=forbidden, close=lambda: None)
    assembly = SimpleNamespace(legacy_sqlite=False, management=None)
    result = MemoryRuntime(root / "PRIVATE_DATABASE.sqlite3", method=engine, backend_assembly=assembly)
    result.status = forbidden
    return result


@asynccontextmanager
async def production(**options):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8767, 8768, 8000, 8003, 18000, 18003, 18770}
    async def close():
        pass
    app = server.create_app(port=port, bridge=SimpleNamespace(close=close), **options)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.SockSite(runner, sock).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            yield client, f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()
        sock.close()


async def login(client, base):
    response = await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})
    assert response.status == 200


def test_assembled_identity_without_sdk_status_database_or_private_path(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    selected = runtime(tmp_path)
    async def check():
        async with production(memory_runtime=selected) as (client, base):
            # 应用构造完成后禁止任何SQLite连接；观察请求自身不能触库。
            monkeypatch.setattr(sqlite3, "connect", forbidden)
            url = base + "/api/memory-engine/identity"
            assert (await client.get(url)).status == 401
            await login(client, base)
            assert (await client.get(url + "?path=private")).status == 400
            assert (await client.get(url, data="private")).status == 400
            response = await client.get(url)
            body = await response.text()
            assert response.status == 200 and "PRIVATE_DATABASE" not in body
            result = await response.json()
            assert result == {"schema_version": 1, "configured": True,
                "method": "hy_memory_pro_chat",
                "representation": "method_defined",
                "legacy_sqlite": False, "state": "available"}
    try:
        asyncio.run(check())
        assert not selected.database.exists()
    finally:
        selected.close()


def test_identity_busy_returns_before_held_chat_lock_and_closed_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    selected = runtime(tmp_path)
    held, release = Event(), Event()
    def hold():
        with selected._lock:
            held.set()
            assert release.wait(10)
    thread = Thread(target=hold)
    thread.start()
    async def check(expected):
        async with production(memory_runtime=selected) as (client, base):
            await login(client, base)
            response = await client.get(base + "/api/memory-engine/identity")
            assert response.status == 503
            assert await response.json() == {"error": expected}
    try:
        assert held.wait(2)
        asyncio.run(check("memory_identity_busy"))
        assert not release.is_set()
    finally:
        release.set()
        thread.join(2)
        selected.close()
    asyncio.run(check("memory_identity_unavailable"))


@pytest.mark.parametrize("standard", [True, False])
def test_hy_catalog_through_real_server_peek_stays_read_only(tmp_path, monkeypatch, standard):
    from longmemory.methods.hy_memory.method import HyMemoryMethod, HyAdministration
    from longmemory.methods.hy_memory.settings import HySettings

    monkeypatch.setattr(server, "ROOT", tmp_path)
    method = HyMemoryMethod(settings=HySettings(user_id="synthetic-user"), client_factory=forbidden)
    if standard:
        method._mechanism_profile = "standard_worker"
    admin = HyAdministration(method)
    selected = MemoryRuntime(tmp_path / "PRIVATE_NEVER_OPENED.sqlite3", method=method,
        backend_assembly=SimpleNamespace(legacy_sqlite=False, management=admin))
    selected.status = forbidden
    selected._round_screen_store = SimpleNamespace(expire=forbidden)

    async def check():
        async with production(memory_runtime=selected) as (client, base):
            monkeypatch.setattr(sqlite3, "connect", forbidden)
            await login(client, base)
            identity = await client.get(base + "/api/memory-engine/identity")
            assert identity.status == 200
            assert (await identity.json())["method"] == "hy_memory_pro_chat"
            response = await client.get(base + "/api/memory-engine/hy/mechanisms")
            assert response.status == 200
            result = await response.json()
            assert result["assembly"] == ("standard_worker" if standard else "custom_or_unknown")
            assert result["mode"] == ("pro" if standard else None)
            assert len(result["layers"]) == 8 and len(result["mechanisms"]) == 46
            assert result["runtime"] == {"engine_initialized": False, "worker_health": "unknown",
                "write_enabled": True, "use_enabled": True}
            assert method._client is None
            assert "PRIVATE_NEVER_OPENED" not in await response.text()
    try:
        asyncio.run(check())
        assert not selected.database.exists()
    finally:
        selected._round_screen_store = None
        selected.close()
