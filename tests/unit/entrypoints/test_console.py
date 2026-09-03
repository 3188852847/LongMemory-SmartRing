"""真实回环 HTTP + 模拟控制桥，不读取个人记忆、不向物理设备发指令。"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="网页测试需要 uv sync --extra console")
from aiohttp import web
from longmemory.entrypoints.api.server import create_app
from longmemory.adapters.device_control.xiaozhi import BridgeError


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.error = None
        self.wait = None
        self.closed = False

    async def status(self):
        if self.error:
            raise self.error
        return {"connection_count": 1, "ready": True, "read_volume_supported": True,
                "set_volume_supported": True, "allowed_volume": {"minimum": 5, "maximum": 60}}

    async def read_volume(self):
        self.calls.append("read")
        if self.wait:
            await self.wait.wait()
        if self.error:
            raise self.error
        return {"volume": 25}

    async def set_volume(self, volume):
        self.calls.append(volume)
        if self.error:
            raise self.error
        return {"requested_volume": volume, "previous_volume": 25,
                "acknowledged": True, "readback_volume": volume, "verified": True}

    async def close(self):
        self.closed = True


@asynccontextmanager
async def console(database=None, allow_memory_delete=False, chat_backend=None):
    # 先占用随机回环端口，再把精确 Host 交给应用，避免探测后抢占端口。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    bridge = FakeBridge()
    runner = web.AppRunner(create_app(port=port, bridge=bridge, database=database,
                                     allow_memory_delete=allow_memory_delete, chat_backend=chat_backend), access_log=None)
    await runner.setup()
    await web.SockSite(runner, sock).start()
    try:
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False) as client:
            yield client, f"http://127.0.0.1:{port}", bridge
    finally:
        await runner.cleanup()
    assert bridge.closed


async def login(client, base):
    response = await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})
    assert response.status == 200
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    return {"Origin": base, "X-Console-CSRF": (await response.json())["csrf"]}


def test_console_serves_only_local_assets_and_protected_device_actions():
    async def run():
        async with console() as (client, base, bridge):
            for path in ("/", "/assets/console.css", "/assets/app.js", "/assets/state.mjs", "/assets/favicon.svg"):
                response = await client.get(base + path)
                assert response.status == 200
                assert "default-src 'none'" in response.headers["Content-Security-Policy"]
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Frame-Options"] == "DENY"
            for path in ("/.env", "/data/control/device-control.token", "/assets/README.md", "/api/arbitrary-tool"):
                assert (await client.get(base + path)).status in {401, 404}
            assert (await client.get(base + "/api/session")).status == 403
            assert (await client.get(base + "/api/device")).status == 401
            headers = await login(client, base)
            response = await client.get(base + "/api/device")
            assert (await response.json())["ready"] is True
            assert bridge.calls == []  # 连接轮询不发设备命令。
            assert (await (await client.get(base + "/api/device/volume")).json()) == {"volume": 25}
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 200
            assert (await response.json())["verified"] is True
            assert bridge.calls == ["read", 30]
    asyncio.run(run())


@pytest.mark.parametrize("attack", ["no_csrf", "no_origin", "other_origin", "other_host", "cross_site", "same_site", "wrong_cookie"])
def test_console_rejects_browser_attacks_without_calling_device(attack):
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            if attack == "no_csrf": headers.pop("X-Console-CSRF")
            if attack == "no_origin": headers.pop("Origin")
            if attack == "other_origin": headers["Origin"] = "https://evil.invalid"
            if attack == "other_host": headers["Host"] = "evil.invalid"
            if attack == "cross_site": headers["Sec-Fetch-Site"] = "cross-site"
            if attack == "same_site": headers["Sec-Fetch-Site"] = "same-site"
            if attack == "wrong_cookie": client.cookie_jar.clear()
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status in {401, 403}
            assert bridge.calls == []
            assert "Access-Control-Allow-Origin" not in response.headers
    asyncio.run(run())


@pytest.mark.parametrize("body", [{"volume": True}, {"volume": 4}, {"volume": 61}, {"volume": 30.1}, {"volume": "30"}, {}, [], {"volume": 30, "tool": "evil"}])
def test_console_rejects_invalid_volume(body):
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            response = await client.post(base + "/api/device/volume", headers=headers, json=body)
            assert response.status == 400
            assert bridge.calls == []
    asyncio.run(run())


def test_console_limits_body_and_does_not_retry_uncertain_write():
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            response = await client.post(base + "/api/device/volume", headers=headers, data="volume=30")
            assert response.status == 400
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": "x" * 2000})
            assert response.status == 413
            assert bridge.calls == []
            bridge.error = BridgeError("device_timeout_outcome_unknown", 504)
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 504
            assert (await response.json())["error"] == "device_timeout_outcome_unknown"
            assert bridge.calls == [30]
    asyncio.run(run())


def test_console_serializes_device_operations():
    async def run():
        async with console() as (client, base, bridge):
            headers = await login(client, base)
            bridge.wait = asyncio.Event()
            first = asyncio.create_task(client.get(base + "/api/device/volume"))
            for _ in range(100):
                if bridge.calls: break
                await asyncio.sleep(0.005)
            assert bridge.calls == ["read"]
            response = await client.post(base + "/api/device/volume", headers=headers, json={"volume": 30})
            assert response.status == 409
            assert bridge.calls == ["read"]
            bridge.wait.set()
            assert (await first).status == 200
    asyncio.run(run())


def test_memory_http_browse_sources_confirmed_delete_and_persistence(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "synthetic.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, True) as (client, base, _bridge):
            assert (await client.get(base + "/memories")).status == 200
            assert (await client.get(base + "/api/memories")).status == 401
            headers = await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config["database"] == str(database.resolve())
            assert config["allow_delete"] is True
            listed = await (await client.get(base + "/api/memories?q=豆包")).json()
            assert listed["total"] == 1
            assert "sources" not in listed["items"][0]
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            assert details["sources"][0]["message"]["content"] == "我养了一只叫豆包的猫。"
            body = {"revision": details["revision"], "confirm_delete": True}
            assert (await client.delete(url, json=body)).status == 403
            assert (await client.delete(url, headers={**headers, "Origin": "https://evil.invalid"}, json=body)).status == 403
            assert (await client.delete(url, headers=headers, json={**body, "confirm_delete": False})).status == 400
            response = await client.delete(url, headers=headers, json=body)
            assert response.status == 200
            assert (await response.json())["l0_preserved"] is True
            assert (await client.get(url)).status == 404
            assert (await client.delete(url, headers=headers, json=body)).status == 404
    asyncio.run(run())
    reopened = build_application(database_path=database)
    assert reopened.get_memory(result.saved_memories[0].id) is None
    assert reopened.chat("我的猫叫什么？").retrieved_memories == ()
    reopened.close()
    import sqlite3
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT content FROM conversation_messages WHERE id=?", (str(result.user_message.id),)).fetchone()[0] == "我养了一只叫豆包的猫。"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=100001", "state=unknown", "database=other.db", "limit=1&limit=2", "limit=no", "q=" + "x" * 201])
def test_memory_query_validation(query):
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memories?" + query)).status == 400
    asyncio.run(run())


def test_memory_without_config_is_not_a_fake_empty_database():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config == {"configured": False, "database": None, "allow_delete": False}
            response = await client.get(base + "/api/memories")
            assert response.status == 503
            assert (await response.json())["error"] == "memory_not_configured"
            # 缺少记忆库时，设备页仍然工作，不制造两条链路之间的耦合。
            assert (await client.get(base + "/api/device")).status == 200
    asyncio.run(run())
