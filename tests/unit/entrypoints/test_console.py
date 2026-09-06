"""真实回环 HTTP + 模拟控制桥，不读取个人记忆、不向物理设备发指令。"""

import asyncio
import socket
import sqlite3
from contextlib import asynccontextmanager

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="网页测试需要 uv sync --extra console")
pydantic = pytest.importorskip("pydantic", reason="网页契约测试需要 uv sync --extra console")
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
async def console(database=None, allow_memory_delete=False, chat_backend=None,
                  allow_memory_correction=False, allow_scenario_management=False,
                  xiaozhi_server=None, memory_runtime_token=None,
                  scenario_producer=None, scenario_model=None):
    # 先占用随机回环端口，再把精确 Host 交给应用，避免探测后抢占端口。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    bridge = FakeBridge()
    runner = web.AppRunner(create_app(port=port, bridge=bridge, database=database,
                                     allow_memory_delete=allow_memory_delete, chat_backend=chat_backend,
                                     allow_memory_correction=allow_memory_correction,
                                     allow_scenario_management=allow_scenario_management,
                                     xiaozhi_server=xiaozhi_server,
                                     memory_runtime_token=memory_runtime_token,
                                     scenario_producer=scenario_producer,
                                     scenario_model=scenario_model), access_log=None)
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
            source_id = details["sources"][0]["source_message_id"]
            l0 = await (await client.get(base + "/api/source-messages?link_state=linked")).json()
            assert l0["total"] >= 1 and any(item["id"] == source_id for item in l0["items"])
            l0_detail = await (await client.get(base + "/api/source-messages/" + source_id)).json()
            assert l0_detail["derived_memories"][0]["id"] == memory_id
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


def test_memory_http_correction_requires_explicit_semantics_and_confirmation(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "correction.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, allow_memory_correction=True) as (client, base, _bridge):
            headers = await login(client, base)
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            body = {"revision": details["revision"], "corrected_content": "用户的猫叫年糕。",
                    "correction_kind": "error", "confirm_correction": True}
            assert (await client.post(url + "/corrections", json=body)).status == 403
            assert (await client.post(url + "/corrections", headers=headers,
                                      json={**body, "correction_kind": "change"})).status == 400
            assert (await client.post(url + "/corrections", headers=headers,
                                      json={**body, "confirm_correction": False})).status == 400
            response = await client.post(url + "/corrections", headers=headers, json=body)
            assert response.status == 200
            written = await response.json()
            assert written["source_type"] == "user_corrected"
            old = await (await client.get(url)).json()
            new = await (await client.get(base + "/api/memories/" + written["new_memory_id"])).json()
            assert old["state"] == "retired" and old["superseded_by_id"] == new["id"]
            assert new["content"] == "用户的猫叫年糕。"

    asyncio.run(run())


def test_memory_http_fact_change_requires_explicit_semantics_and_time(tmp_path):
    from longmemory.bootstrap import build_application
    database = tmp_path / "fact-change.db"
    app = build_application(database_path=database)
    result = app.chat("我养了一只叫豆包的猫。")
    memory_id = str(result.saved_memories[0].id)
    app.close()

    async def run():
        async with console(database, allow_memory_correction=True) as (client, base, _bridge):
            headers = await login(client, base)
            url = base + "/api/memories/" + memory_id
            details = await (await client.get(url)).json()
            body = {
                "revision": details["revision"],
                "new_content": "用户现在养了一只叫年糕的猫。",
                "effective_at": "2026-09-03T12:00:00+00:00",
                "change_kind": "fact_changed",
                "confirm_change": True,
            }
            assert (await client.post(url + "/changes", json=body)).status == 403
            assert (await client.post(
                url + "/changes", headers=headers,
                json={**body, "change_kind": "error"},
            )).status == 400
            assert (await client.post(
                url + "/changes", headers=headers,
                json={**body, "effective_at": "2026-09-03T12:00:00"},
            )).status == 400
            response = await client.post(url + "/changes", headers=headers, json=body)
            assert response.status == 200
            written = await response.json()
            old = await (await client.get(url)).json()
            new = await (await client.get(
                base + "/api/memories/" + written["new_memory_id"]
            )).json()
            assert old["valid_to"] == body["effective_at"]
            assert new["valid_from"] == body["effective_at"]
            assert new["sources"][0]["source_type"] == "user_stated"

    asyncio.run(run())


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=100001", "state=unknown", "database=other.db", "limit=1&limit=2", "limit=no", "q=" + "x" * 201])
def test_memory_query_validation(query):
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memories?" + query)).status == 400
    asyncio.run(run())


@pytest.mark.parametrize("query", [
    "limit=0", "limit=101", "offset=-1", "role=system", "link_state=unknown",
    "role=user&role=assistant", "q=" + "x" * 201,
])
def test_source_message_query_validation(query):
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/source-messages?" + query)).status == 400
    asyncio.run(run())


def test_memory_without_config_is_not_a_fake_empty_database():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            config = await (await client.get(base + "/api/memory-config")).json()
            assert config == {"configured": False, "database": None, "allow_delete": False,
                              "allow_correction": False, "allow_change": False,
                              "allow_scenario_management": False,
                              "scenario_model_preview_available": False,
                              "scenario_model": None}
            response = await client.get(base + "/api/memories")
            assert response.status == 503
            assert (await response.json())["error"] == "memory_not_configured"
            # 缺少记忆库时，设备页仍然工作，不制造两条链路之间的耦合。
            assert (await client.get(base + "/api/device")).status == 200
    asyncio.run(run())


def test_internal_runtime_requires_token_and_is_immediately_shared_with_web(tmp_path):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "shared-runtime.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "a" * 64

    async def run():
        async with console(database, chat_backend=backend, memory_runtime_token=token) as (client, base, _bridge):
            endpoint = base + "/api/internal/memory/prepare"
            body = {"version": 1, "query": "我养了一只叫豆包的猫"}
            assert (await client.post(endpoint, json=body)).status == 401
            assert (await client.post(endpoint, headers={"Authorization": "Bearer wrong"}, json=body)).status == 401
            response = await client.post(endpoint, headers={"Authorization": "Bearer " + token}, json=body)
            assert response.status == 200
            written = await response.json()
            assert written["added"] == 1 and "豆包" in written["context"]

            # 网页后端没有另开一套运行时；同一进程立刻读取圆屏刚写入的事实。
            recalled = await asyncio.to_thread(backend.run, "我的猫叫什么", ())
            assert recalled["status"] == "completed" and "豆包" in recalled["answer"]
            assert recalled["retrieved"][0]["source_event_ids"] == (written["turn_id"],)

    asyncio.run(run())


def test_memory_mode_http_controls_the_shared_web_and_voice_runtime(tmp_path):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "memory-mode.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())
    token = "b" * 64

    async def run():
        async with console(database, chat_backend=backend, memory_runtime_token=token) as (client, base, _bridge):
            headers = await login(client, base)
            current = await client.get(base + "/api/memory-mode")
            assert current.status == 200
            assert await current.json() == {
                "write_enabled": True,
                "use_enabled": True,
                "scenario_use_enabled": False,
                "scenario_available": True,
                "persistent": False,
                "l0_archived_when_write_disabled": True,
            }

            # 修改状态属于受保护操作，必须来自本机已建立的控制台会话。
            body = {"write_enabled": False, "use_enabled": False,
                    "scenario_use_enabled": True}
            assert (await client.put(base + "/api/memory-mode", headers={"Origin": base}, json=body)).status == 403
            changed = await client.put(base + "/api/memory-mode", headers=headers, json=body)
            assert changed.status == 200
            assert (await changed.json())["persistent"] is False

            # 同一个 Runtime 立即影响内部小智接口，并清楚回报本轮未写、未召回。
            voice = await client.post(
                base + "/api/internal/memory/prepare",
                headers={"Authorization": "Bearer " + token},
                json={"version": 1, "query": "我喜欢暮雪饮料"},
            )
            assert voice.status == 200
            payload = await voice.json()
            assert payload["memory_write_enabled"] is False
            assert payload["memory_use_enabled"] is False
            assert payload["scenario_use_enabled"] is True
            assert payload["scenario_retrieved"] == []
            assert payload["added"] == 0 and payload["retrieved"] == 0
            assert payload["context"] == ""
            assert payload["retrieval_strategy"] == "disabled_by_user"

            web_result = await asyncio.to_thread(backend.run, "我喜欢青色", ())
            assert web_result["writes"] == []
            assert web_result["memory_context"] == ""

    asyncio.run(run())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"write_enabled": True},
        {"write_enabled": True, "use_enabled": True, "extra": False},
        {"write_enabled": 1, "use_enabled": True},
        {"write_enabled": True, "use_enabled": "false"},
        [],
    ],
)
def test_memory_mode_http_rejects_invalid_bodies(tmp_path, body):
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "invalid-memory-mode.db"
    LongMemoryV1(database).close()
    backend = ChatBackend(database, FakeAnswerGenerator())

    async def run():
        async with console(database, chat_backend=backend) as (client, base, _bridge):
            headers = await login(client, base)
            response = await client.put(base + "/api/memory-mode", headers=headers, json=body)
            assert response.status == 400
            status = backend.memory_runtime().status()
            assert status["write_enabled"] is True and status["use_enabled"] is True

    asyncio.run(run())


def test_memory_mode_reports_chat_disabled_instead_of_fake_state():
    async def run():
        async with console() as (client, base, _bridge):
            await login(client, base)
            assert (await client.get(base + "/api/memory-mode")).status == 503

    asyncio.run(run())


def test_scenario_http_requires_csrf_and_explicit_capability(tmp_path):
    from longmemory.methods.longmemory_v1.method import LongMemoryV1

    database = tmp_path / "scenario-http.db"
    LongMemoryV1(database).close()
    with sqlite3.connect(database) as connection:
        for suffix, content in (("a", "用户周五答辩。"), ("b", "用户正在修改 PPT。")):
            connection.execute(
                "INSERT INTO conversation_messages VALUES (?,?,?,?)",
                (f"l0-{suffix}", "user", content, "2026-09-06T10:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO atomic_memories VALUES (?,?,?,?,NULL,NULL,NULL,NULL)",
                (f"l1-{suffix}", "user:self", content, "2026-09-06T10:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO memory_evidence VALUES (?,?,?,?)",
                (f"l1-{suffix}", f"l0-{suffix}", "user_stated", "2026-09-06T10:00:00+00:00"),
            )

    class ProposalProducer:
        calls = 0

        def propose(self, *, sources):
            self.calls += 1
            return ('{"schema_version":1,"candidate":{"title":"准备答辩",'
                    '"summary":"用户最近正在准备答辩并修改 PPT。",'
                    '"source_memory_ids":["l1-a","l1-b"]}}')

    producer = ProposalProducer()

    async def run():
        async with console(database, allow_scenario_management=True,
                           scenario_producer=producer, scenario_model="synthetic-model") as (client, base, _bridge):
            headers = await login(client, base)
            proposal_body = {"source_memory_ids": ["l1-a", "l1-b"],
                             "confirm_model_call": True}
            assert (await client.post(base + "/api/scenario-proposals", json=proposal_body)).status == 403
            proposal_response = await client.post(
                base + "/api/scenario-proposals", headers=headers, json=proposal_body
            )
            proposal = await proposal_response.json()
            assert proposal_response.status == 200
            assert proposal["persisted"] is False and proposal["model"] == "synthetic-model"
            assert producer.calls == 1
            assert (await (await client.get(base + "/api/scenarios?state=all")).json())["total"] == 0
            inbox_before = await (
                await client.get(base + "/api/scenario-source-inbox")
            ).json()
            assert inbox_before["total"] == 2
            assert inbox_before["selection_is_semantic"] is False
            body = {"title": "准备答辩", "summary": "用户最近正在准备答辩。",
                    "source_memory_ids": ["l1-a", "l1-b"], "creation_kind": "manual",
                    "confirm_candidate": True,
                    "valid_from": "2026-09-06T08:00:00+00:00",
                    "valid_to": "2026-09-13T08:00:00+00:00"}
            assert (await client.post(base + "/api/scenarios", json=body)).status == 403
            created_response = await client.post(base + "/api/scenarios", headers=headers, json=body)
            assert created_response.status == 200
            created = await created_response.json()
            assert (await (
                await client.get(base + "/api/scenario-source-inbox")
            ).json())["total"] == 0
            listed = await (await client.get(base + "/api/scenarios?state=candidate")).json()
            assert listed["total"] == 1
            detail = await (await client.get(base + "/api/scenarios/" + created["id"])).json()
            assert detail["valid_from"] == "2026-09-06T08:00:00+00:00"
            assert detail["valid_to"] == "2026-09-13T08:00:00+00:00"
            assert {source["l0_sources"][0]["content"] for source in detail["sources"]} == {
                "用户周五答辩。", "用户正在修改 PPT。",
            }
            reviewed = await client.post(
                base + "/api/scenarios/" + created["id"] + "/reviews",
                headers=headers,
                json={"decision": "accepted", "expected_revision": detail["revision"],
                      "confirm_review": True},
            )
            assert reviewed.status == 200 and (await reviewed.json())["status"] == "active"
            lifecycle_url = base + "/api/scenarios/" + created["id"] + "/lifecycle"
            lifecycle_body = {
                "action": "manual_end", "expected_revision": 2, "confirm_action": True,
            }
            assert (await client.post(lifecycle_url, json=lifecycle_body)).status == 403
            ended_response = await client.post(
                lifecycle_url, headers=headers, json=lifecycle_body,
            )
            ended = await ended_response.json()
            assert ended_response.status == 200
            assert ended["status"] == "stale" and ended["revision"] == 3
            ended_detail = await (
                await client.get(base + "/api/scenarios/" + created["id"])
            ).json()
            assert ended_detail["lifecycle_events"][0]["action"] == "manual_end"
            assert len(ended_detail["sources"]) == 2

    asyncio.run(run())
