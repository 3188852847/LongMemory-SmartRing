"""Z cross-boundary checks: real Runtime/HTTP/SDK, synthetic model, no paid calls."""

import asyncio
from datetime import UTC, datetime
import os
from pathlib import Path
import socket
from uuid import uuid4

from aiohttp import ClientSession, CookieJar, web
import pytest

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.entrypoints.api.routes.memory_engine import register_memory_engine_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.administration import HyManagementUncertain
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.assembly import management_primitives_identity


SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason="explicit owner-installed SDK required")
EVENT = MemoryEvent("z-release-seed", "user", "合成用户喜欢无糖乌龙茶", datetime(2026, 10, 19, tzinfo=UTC), "z-synthetic-session")


def runtime_at(directory, *, create):
    runtime = build_hy_memory_runtime(settings=HySettings(user_id="z-release-synthetic", model_mode="synthetic_transport", management_writes_enabled=True),
        state_directory=directory / "Hy状态", source_path=directory / "来源.db", create=create, python=SDK,
        management_verification={"sdk_version":"2.0.3", "rpc_source_sha256":management_primitives_identity(),
            "real_sdk_rpc_verified":True, "semantic_background_writes_disabled":True})
    # Test fixture explicitly proves the sole owner and opts into the same trusted
    # serialized management prerequisite; HTTP cannot change this flag.
    admin = runtime.backend_assembly.management
    assert admin.method._client.state._lease is not None
    assert admin.serialized_writes
    return runtime


async def with_http(runtime, check):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port not in {8767, 8000, 8003}
    base = f"http://127.0.0.1:{port}"
    sessions = Sessions()
    app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])

    async def session(_request):
        identity, csrf = sessions.create()
        response = web.json_response({"csrf": csrf})
        response.set_cookie("lm_console_session", identity, httponly=True)
        return response

    app.router.add_get("/api/session", session)
    register_memory_engine_routes(app, runtime, allow_correction=True, allow_delete=True)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        await web.SockSite(runner, sock).start()
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
            csrf = await (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).json()
            await check(client, base + "/api/memory-engine", {"Origin": base, "X-Console-CSRF": csrf["csrf"]})
    finally:
        await runner.cleanup()
        sock.close()


def test_real_http_sdk_correction_source_replay_pause_and_isolated_delete(tmp_path):
    runtime = runtime_at(tmp_path, create=True)
    try:
        assert runtime._method.observe(EVENT).processing_status == "completed"

        async def check(client, prefix, headers):
            listing = await (await client.get(prefix + "/items")).json()
            assert listing["total"] == 1
            item = listing["items"][0]
            assert item["source_event_ids"] == [EVENT.event_id]
            caps = await (await client.get(prefix + "/hy/workspace")).json()
            assert caps["correction"] is True and caps["deletion"] is True
            assert caps["native_atomic_revision"] is False
            request_id = str(uuid4())
            content = "合成用户现在喜欢无糖茉莉花茶"
            body = {"request_id": request_id, "revision": item["revision"], "content": content}
            url = prefix + f"/hy/items/{item['item_id']}/corrections"
            assert (await client.post(url, json=body)).status == 403
            result = await client.post(url, headers=headers, json=body)
            assert result.status == 200, await result.text()
            first = await result.json()
            assert first["state"] == "completed" and first["replayed"] is False
            source_id = "hy-management:" + request_id
            source = runtime.source_detail(source_id)
            assert source["role"] == "user" and source["content"] == content
            assert source["state"] == "archived"
            result = await client.post(url, headers=headers, json=body)
            assert result.status == 200 and (await result.json())["replayed"] is True
            assert runtime.source_detail(source_id) == source
            assert (await client.post(url, headers=headers, json={**body, "content": "异载荷"})).status == 409
            support = runtime._method.recall("合成用户喜欢什么茶")
            assert any(content in row.content and source_id in row.source_event_ids for row in support.retrieved)
            changed = await (await client.get(prefix + f"/items/{item['item_id']}")).json()
            assert changed["content"] == content and changed["revision"] != item["revision"]
            stale = await client.post(url, headers=headers, json={**body, "request_id": str(uuid4())})
            assert stale.status == 409
            runtime.configure(write_enabled=False, use_enabled=True)
            assert not (await (await client.get(prefix + "/hy/workspace")).json())["correction"]
            assert (await client.post(url, headers=headers, json={**body, "request_id": str(uuid4())})).status == 403
            runtime.configure(write_enabled=True, use_enabled=True)
            deletion = {"request_id": str(uuid4()), "revision": changed["revision"], "confirmation": "删除这条记忆"}
            removed = await client.post(prefix + f"/hy/items/{item['item_id']}/deletion", headers=headers, json=deletion)
            assert removed.status == 200, await removed.text()
            assert (await client.get(prefix + f"/items/{item['item_id']}")).status == 404
            assert runtime.source_detail(EVENT.event_id)["content"] == EVENT.content
            assert runtime.source_detail(source_id) == source

        asyncio.run(with_http(runtime, check))
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    finally:
        runtime.close()
    reopened = runtime_at(tmp_path, create=False)
    try:
        assert reopened.administer("listing", "list_items").total == 0
        operations = reopened.administer_extension("hy_memory", "operations")
        assert operations["total"] == 2 and all(row["state"] == "completed" for row in operations["items"])
    finally:
        reopened.close()


def test_real_sdk_readback_failure_remains_uncertain_after_restart(tmp_path, monkeypatch):
    runtime = runtime_at(tmp_path, create=True)
    try:
        runtime._method.observe(EVENT)
        item = runtime.administer("listing", "list_items").items[0]
        engine = runtime._method.engine
        original = engine.sdk_call
        updated = False

        def break_readback(operation, **arguments):
            nonlocal updated
            if updated and operation == "get":
                raise OSError("synthetic readback interruption after real SDK commit")
            result = original(operation, **arguments)
            if operation == "update":
                updated = True
            return result

        monkeypatch.setattr(engine, "sdk_call", break_readback)
        request_id = str(uuid4())
        source = MemoryEvent("hy-management:" + request_id, "user", "合成用户现在喜欢红茶", datetime.now(UTC))
        with pytest.raises(HyManagementUncertain, match="hy_management_outcome_uncertain"):
            runtime.administer_extension("hy_memory", "correct", item_id=item.item_id,
                request_id=request_id, expected_revision=item.revision, source=source, content=source.content)
        monkeypatch.setattr(engine, "sdk_call", original)
        assert original("get", memory_id=item.item_id)["content"] == source.content
    finally:
        runtime.close()
    reopened = runtime_at(tmp_path, create=False)
    try:
        operations = reopened.administer_extension("hy_memory", "operations")
        assert operations["items"][0]["state"] == "uncertain"
        assert reopened._method.recall("合成用户喜欢什么茶").retrieved == ()
        current = reopened.administer("detail", "get_item", item.item_id)
        later = str(uuid4())
        with pytest.raises(HyManagementUncertain, match="hy_management_outcome_uncertain"):
            reopened.administer_extension("hy_memory", "correct", item_id=item.item_id,
                request_id=later, expected_revision=current.revision,
                source=MemoryEvent("hy-management:" + later, "user", "合成用户喜欢白茶", datetime.now(UTC)),
                content="合成用户喜欢白茶")
        assert reopened._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    finally:
        reopened.close()
