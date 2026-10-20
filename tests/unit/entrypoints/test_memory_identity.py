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


def lazy_backend(root):
    backend = ChatBackend(root / "synthetic-sidecar-base.sqlite3", generator=SimpleNamespace(generate=forbidden))
    backend.memory_runtime = forbidden
    return backend


def runtime(root, legacy=False):
    engine = SimpleNamespace(name="longmemory_daily_llm_v2" if legacy else "hy_memory_pro_chat",
        wait_until_ready=forbidden, close=lambda: None)
    assembly = None if legacy else SimpleNamespace(legacy_sqlite=False, management=None)
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
    app = server.create_app(port=port, bridge=SimpleNamespace(close=close), proactive_schedule_enabled=False, **options)
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


@pytest.mark.parametrize("legacy", [False, True])
def test_assembled_identity_without_sdk_status_database_or_private_path(tmp_path, monkeypatch, legacy):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    selected = runtime(tmp_path, legacy)
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
                "method": "longmemory_daily_llm_v2" if legacy else "hy_memory_pro_chat",
                "representation": "atomic_fact" if legacy else "method_defined",
                "legacy_sqlite": legacy, "state": "available"}
    try:
        asyncio.run(check())
        assert not selected.database.exists()
    finally:
        selected.close()


@pytest.mark.parametrize("configured", [False, True])
def test_uninitialized_and_unconfigured_are_distinct_and_do_not_lazy_create(tmp_path, monkeypatch, configured):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    backend = lazy_backend(tmp_path)
    async def check():
        async with production(chat_backend=backend,
                database=tmp_path / "PRIVATE_MISSING.sqlite3" if configured else None) as (client, base):
            monkeypatch.setattr(sqlite3, "connect", forbidden)
            await login(client, base)
            response = await client.get(base + "/api/memory-engine/identity")
            assert response.status == 200
            assert await response.json() == {"schema_version": 1, "configured": configured,
                "method": None, "representation": "atomic_fact" if configured else None,
                "legacy_sqlite": True if configured else None,
                "state": "not_initialized" if configured else "unconfigured"}
            # Hy观察端点也不能借普通selector懒创建旧引擎。
            assert (await client.get(base + "/api/memory-engine/hy/mechanisms")).status == 503
    asyncio.run(check())
    assert backend._runtime is None
    assert not (tmp_path / "PRIVATE_MISSING.sqlite3").exists()


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


def test_identity_rechecks_lazy_backend_reference_without_initializing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    backend = lazy_backend(tmp_path)
    selected = runtime(tmp_path, legacy=True)
    async def check():
        async with production(chat_backend=backend, database=selected.database) as (client, base):
            await login(client, base)
            url = base + "/api/memory-engine/identity"
            assert (await (await client.get(url)).json())["state"] == "not_initialized"
            backend._runtime = selected
            assert (await (await client.get(url)).json())["method"] == "longmemory_daily_llm_v2"
    try:
        asyncio.run(check())
    finally:
        selected.close()
