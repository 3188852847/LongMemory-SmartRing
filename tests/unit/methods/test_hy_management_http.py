"""真实 HTTP/安全中间件；Runtime 扩展为显式替身，不冒称 X 接线已验收。"""

import asyncio
from datetime import datetime
import socket
from uuid import uuid4

from aiohttp import ClientSession, CookieJar, web

from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.hy_memory.administration import HyManagementConflict, HyManagementUncertain


class Runtime:
    def __init__(self): self.calls = []; self.write = True; self.error = None
    def status(self):
        return {"method": "hy_memory_pro_chat", "management_capabilities": {}, "write_enabled": self.write, "use_enabled": True}
    def administer_extension(self, namespace, operation, **arguments):
        self.calls.append((namespace, operation, arguments))
        if self.error: raise self.error
        if operation == "workspace": return {"protocol": 1, "correction": True, "deletion": True}
        if operation in {"correct", "delete"}:
            if not self.write:
                from longmemory.entrypoints.api.errors import MemoryAccessError
                raise MemoryAccessError("memory_write_paused", 403)
            source = arguments["source"]
            assert source.role == "user" and source.event_id == "hy-management:" + arguments["request_id"]
            assert isinstance(source.occurred_at, datetime) and source.occurred_at.utcoffset() is not None
            return {"state": "completed", "request_id": arguments["request_id"], "platform_sources_preserved": True}
        return {"items": [], "total": 0, "offset": arguments.get("offset", 0), "limit": arguments.get("limit", 25)}


async def serve(check, *, correction=True, deletion=True, runtime=None):
    runtime = runtime or Runtime()
    sock = socket.socket(); sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8767, 8000, 8003}
    base = f"http://127.0.0.1:{port}"
    sessions = Sessions()
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])
    async def bootstrap(request):
        session, csrf = sessions.create()
        response = web.json_response({"csrf": csrf})
        response.set_cookie("lm_console_session", session, httponly=True)
        return response
    app.router.add_get('/api/session', bootstrap)
    register_memory_engine_routes(app, runtime, allow_correction=correction, allow_delete=deletion)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup(); await web.SockSite(runner, sock).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            await check(client, base, runtime)
    finally:
        await runner.cleanup(); sock.close()


def test_session_origin_csrf_strict_body_and_real_user_source():
    async def check(client, base, runtime):
        prefix = base + "/api/memory-engine/hy"
        assert (await client.get(prefix + "/workspace")).status == 401
        csrf = await (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).json()
        headers = {"Origin": base, "X-Console-CSRF": csrf["csrf"]}
        body = {"request_id": str(uuid4()), "revision": "a" * 64, "content": "合成用户纠正事实"}
        url = prefix + "/items/synthetic-item/corrections"
        assert (await client.post(url, json=body)).status == 403
        assert (await client.post(url, headers={**headers, "Origin": "https://foreign.invalid"}, json=body)).status == 403
        for extra in ({"event_id": "forged"}, {"role": "assistant"}, {"path": "private.db"}):
            assert (await client.post(url, headers=headers, json={**body, **extra})).status == 400
        assert (await client.post(url + "?source=other", headers=headers, json=body)).status == 400
        assert (await client.get(prefix + "/operations?limit=2&limit=3")).status == 400
        assert (await client.get(prefix + "/profile?user_id=other")).status == 400
        assert (await client.post(url, headers=headers, json=body)).status == 200
        assert runtime.calls[-1][2]["source"].content == body["content"]
        delete = {"request_id": str(uuid4()), "revision": "a" * 64, "confirmation": "删除这条记忆"}
        assert (await client.post(prefix + "/items/synthetic-item/deletion", headers=headers, json=delete)).status == 200
        assert runtime.calls[-1][2]["source"].content == "删除这条记忆：synthetic-item"
    asyncio.run(serve(check))


def test_startup_permissions_runtime_pause_conflict_and_uncertain():
    async def denied(client, base, runtime):
        csrf = await (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).json()
        headers = {"Origin": base, "X-Console-CSRF": csrf["csrf"]}
        info = await (await client.get(base + "/api/memory-engine/hy/workspace")).json()
        assert not info["correction"] and not info["deletion"]
        assert (await client.post(base + "/api/memory-engine/hy/items/id/corrections", headers=headers, json={})).status == 403
    asyncio.run(serve(denied, correction=False, deletion=False))
    async def check(client, base, runtime):
        csrf = await (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).json()
        headers = {"Origin": base, "X-Console-CSRF": csrf["csrf"]}
        url = base + "/api/memory-engine/hy/items/id/corrections"
        body = {"request_id": str(uuid4()), "revision": "a" * 64, "content": "合成纠正"}
        runtime.write = False
        assert not (await (await client.get(base + "/api/memory-engine/hy/workspace")).json())["correction"]
        assert (await client.post(url, headers=headers, json=body)).status == 403
        runtime.write = True; runtime.error = HyManagementConflict("hy_management_revision_conflict")
        assert (await client.post(url, headers=headers, json=body)).status == 409
        runtime.error = HyManagementUncertain("synthetic-private-error")
        result = await client.post(url, headers=headers, json=body)
        assert result.status == 503 and await result.json() == {"error": "hy_management_outcome_uncertain"}
    asyncio.run(serve(check))


def test_missing_runtime_extension_fails_closed():
    async def check(client, base, runtime):
        await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})
        assert (await client.get(base + "/api/memory-engine/hy/workspace")).status == 501
    asyncio.run(serve(check, runtime=object()))
