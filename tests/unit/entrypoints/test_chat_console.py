import asyncio
from uuid import uuid4
import threading

import pytest
pytest.importorskip("aiohttp")

from test_console import console, login
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from longmemory.infrastructure.config.model_profiles import ModelProfileStore
from longmemory.infrastructure.config.memory_backends import MemoryBackendStore


@pytest.fixture
def backend(tmp_path):
    database = tmp_path / "synthetic.db"
    LongMemoryV1(database).close()
    return ChatBackend(database, FakeAnswerGenerator())


def test_chat_disabled_and_static_security():
    async def run():
        async with console() as (client, base, _):
            headers = await login(client, base)
            response = await client.get(base + "/chat")
            assert '/chat-react' in await response.text()
            assert response.status == 200
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
            assert (await (await client.get(base + "/api/chat-config")).json()) == {"enabled": False}
            assert (await client.post(base + "/api/chats", headers=headers)).status == 403
    asyncio.run(run())


def test_chat_replay_reset_and_owner_isolation(backend):
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            chat_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            url = base + f"/api/chats/{chat_id}/messages"
            body = {"text": "我养了一只叫豆包的猫", "request_id": str(uuid4())}
            assert (await client.post(url, json=body)).status == 403
            first = await client.post(url, json=body, headers=headers)
            assert first.status == 200
            saved = await first.json()
            assert saved["status"] == "completed"
            assert await (await client.post(url, json=body, headers=headers)).json() == saved
            assert (await client.post(url, json={**body, "text": "别的内容"}, headers=headers)).status == 409
            response = await client.get(base + f"/api/chats/{chat_id}")
            assert len((await response.json())["turns"]) == 1
            # 同一浏览器新聊天没有上一会话的短期历史，但共用已持久记忆。
            new_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            response = await client.post(base + f"/api/chats/{new_id}/messages", headers=headers,
                                         json={"text": "我的猫叫什么", "request_id": str(uuid4())})
            second = await response.json()
            assert second["history_messages"] == 0 and "豆包" in second["answer"]
            assert (await client.delete(base + f"/api/chats/{new_id}", headers=headers)).status == 200
            client.cookie_jar.clear()
            await login(client, base)
            assert (await client.get(base + f"/api/chats/{chat_id}")).status == 404
    asyncio.run(run())


def test_explicit_model_check_uses_synthetic_text_without_memory_write(backend):
    calls = []
    class Healthy:
        def generate(self, **kwargs):
            calls.append(kwargs)
            return "连接正常"
    backend.provider, backend.model, backend.generator = "openai_compatible", "synthetic", Healthy()
    backend._model_health = {"state": "unchecked", "code": None, "checked_at": None}
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            response = await client.post(base + "/api/chat-model/check", json={}, headers=headers)
            body = await response.json()
            assert response.status == 200 and body["state"] == "available"
            assert calls == [{"query": "请只回复：连接正常", "memory_context": ""}]
            import sqlite3
            with sqlite3.connect(backend.database) as connection:
                assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
    asyncio.run(run())


def test_model_profile_api_is_csrf_protected_and_never_returns_key(tmp_path):
    store = ModelProfileStore(tmp_path, current_profile="campus")
    body = {
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
        "api_key": "synthetic-secret", "timeout_seconds": 30, "max_tokens": 512,
        "allow_http": False, "activate": True,
    }
    async def run():
        async with console(model_profile_store=store) as (client, base, _):
            headers = await login(client, base)
            assert (await client.put(base + "/api/model-profiles/official", json=body)).status == 403
            response = await client.put(base + "/api/model-profiles/official", json=body, headers=headers)
            assert response.status == 200
            text = await response.text()
            assert "synthetic-secret" not in text
            result = await (await client.get(base + "/api/model-profiles")).json()
            assert result["next_start_profile"] == "official"
            assert result["profiles"][1]["api_key_configured"] is True
    asyncio.run(run())


def test_voice_model_selection_and_check_are_explicit_and_keyless(tmp_path):
    store = ModelProfileStore(tmp_path, current_profile="campus")
    store.save("official", {
        "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
        "api_key": "synthetic-secret", "timeout_seconds": 30, "max_tokens": 512,
        "allow_http": False, "activate": False,
    })
    class Voice:
        async def describe(self):
            return {"enabled": True, "selected_profile": store.selected("voice"),
                    "status": "restart_pending"}
        async def select(self, profile):
            store.activate(profile, target="voice")
            return await self.describe()
        async def check(self):
            return {"state": "available", "code": None, "checked_at": "synthetic",
                    "profile": store.selected("voice")}
    async def run():
        async with console(model_profile_store=store, voice_model_profiles=Voice()) as (client, base, _):
            headers = await login(client, base)
            response = await client.put(base + "/api/model-profiles/voice/selection",
                                        json={"profile": "official"}, headers=headers)
            assert response.status == 200
            assert store.selected("voice") == "official"
            checked = await client.post(base + "/api/model-profiles/voice/check",
                                        json={}, headers=headers)
            text = await checked.text()
            assert checked.status == 200 and "synthetic-secret" not in text
    asyncio.run(run())


def test_round_screen_memory_backend_selection_is_deferred_and_csrf_protected(tmp_path):
    store = MemoryBackendStore(tmp_path, current_backend="longmemory")

    class XiaozhiMemory:
        async def describe(self):
            selected = store.selected()
            return {"enabled": True, "selected_backend": selected,
                    "status": "configured" if selected == "longmemory" else "restart_pending"}

        async def select(self, backend):
            store.select(backend)
            return await self.describe()

    async def run():
        async with console(memory_backend_store=store,
                           xiaozhi_memory_backends=XiaozhiMemory()) as (client, base, _):
            headers = await login(client, base)
            url = base + "/api/memory-backends/selection"
            assert (await client.put(url, json={"backend": "xiaozhi_local"})).status == 403
            response = await client.put(url, json={"backend": "xiaozhi_local"}, headers=headers)
            assert response.status == 200
            result = await response.json()
            assert result["current_backend"] == "longmemory"
            assert result["next_start_backend"] == "xiaozhi_local"
            assert result["restart_required"] is True
            assert result["xiaozhi"]["status"] == "restart_pending"
            assert (await client.put(url, json={"backend": "unknown"}, headers=headers)).status == 400

    asyncio.run(run())


@pytest.mark.parametrize("body", [
    {"text": "", "request_id": str(uuid4())},
    {"text": "  ", "request_id": str(uuid4())},
    {"text": 1, "request_id": str(uuid4())},
    {"text": "字" * 1001, "request_id": str(uuid4())},
    {"text": "合成", "request_id": str(uuid4()).upper()},
    {"text": "合成", "request_id": str(uuid4()), "extra": True},
])
def test_chat_input_validation(backend, body):
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            chat_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            response = await client.post(base + f"/api/chats/{chat_id}/messages", headers=headers,
                                         json=body)
            assert response.status == 400
            assert await response.json() == {"error": "invalid_chat_message"}
    asyncio.run(run())


def test_busy_request_is_not_reexecuted_and_history_stays_local(backend):
    entered, release = threading.Event(), threading.Event()
    calls = []
    class Slow:
        def generate_turn(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            assert release.wait(timeout=5)
            return "synthetic answer"
    backend.generator = Slow()
    backend.provider = "openai_compatible"
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            chat_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            url = base + f"/api/chats/{chat_id}/messages"
            body = {"text": "我喜欢猫", "request_id": str(uuid4())}
            first = asyncio.create_task(client.post(url, json=body, headers=headers))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                assert (await client.post(url, json=body, headers=headers)).status == 409
                assert (await client.delete(base + f"/api/chats/{chat_id}", headers=headers)).status == 409
                assert (await client.get(base + "/api/device")).status == 200
            finally:
                release.set()
            assert (await first).status == 200
            assert len(calls) == 1 and calls[0]["history"] == ()
            response = await client.post(url, json={"text": "继续", "request_id": str(uuid4())}, headers=headers)
            assert (await response.json())["status"] == "completed"
            assert calls[1]["history"] == ({"role": "user", "content": "我喜欢猫"}, {"role": "assistant", "content": "synthetic answer"})
    asyncio.run(run())


def test_chinese_body_limit_failed_retry_and_new_chat_preserves_l0(backend):
    calls = []
    class Broken:
        def generate(self, **kwargs):
            from longmemory.application.chat.contracts import AnswerGenerationError
            calls.append(kwargs)
            raise AnswerGenerationError("synthetic")
    backend.generator = Broken()
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            chat_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            url = base + f"/api/chats/{chat_id}/messages"
            body = {"text": "字" * 1000, "request_id": str(uuid4())}
            response = await client.post(url, json=body, headers=headers)
            assert response.status == 200
            result = await response.json()
            assert result["status"] == "failed" and result["user_saved"]
            assert await (await client.post(url, json=body, headers=headers)).json() == result
            assert len(calls) == 1
            assert (await client.post(url, json={**body, "text": "x" * 9000}, headers=headers)).status == 413
            await client.delete(base + f"/api/chats/{chat_id}", headers=headers)
            import sqlite3
            with sqlite3.connect(backend.database) as connection:
                assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 1
    asyncio.run(run())


def test_session_capacity_and_history_window(backend, monkeypatch):
    # 小限额验证边界，避免让测试集为每种边界跑几十次模型替身。
    from longmemory.entrypoints.api.routes import chat as routes
    monkeypatch.setattr(routes, "MAX_CHATS", 1)
    monkeypatch.setattr(routes, "MAX_TURNS", 3)
    monkeypatch.setattr(routes, "HISTORY_PAIRS", 1)
    histories = []
    class Recorder:
        def generate_turn(self, **kwargs):
            histories.append(kwargs["history"])
            return "synthetic"
    backend.provider, backend.generator = "openai_compatible", Recorder()
    async def run():
        async with console(chat_backend=backend) as (client, base, _):
            headers = await login(client, base)
            chat_id = (await (await client.post(base + "/api/chats", headers=headers)).json())["chat_id"]
            assert (await client.post(base + "/api/chats", headers=headers)).status == 429
            for number in range(4):
                response = await client.post(base + f"/api/chats/{chat_id}/messages", headers=headers,
                                             json={"text": f"合成问题{number}", "request_id": str(uuid4())})
                assert response.status == (200 if number < 3 else 409)
            assert len(histories) == 3 and len(histories[2]) == 2
            assert histories[2][0]["content"] == "合成问题1"
    asyncio.run(run())
