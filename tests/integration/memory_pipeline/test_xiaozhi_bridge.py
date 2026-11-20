"""离线验证真实子进程/SQLite，以及小智 Memory 插槽的最小接口。"""

import asyncio
import ast
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import URLError
from types import ModuleType, SimpleNamespace

import pytest

from longmemory.entrypoints.xiaozhi.mapping import extract_user_text


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider_class(monkeypatch):
    # 直接验证项目适配器，只替换第三方基类和日志。
    base = ModuleType("core.providers.memory.base")

    class Base:
        def __init__(self, config):
            self.config, self.role_id = config, None

        def init_memory(self, role_id, llm, **kwargs):
            self.role_id, self.llm = role_id, llm

    base.MemoryProviderBase = Base
    base.logger = SimpleNamespace(bind=lambda **kwargs: SimpleNamespace(info=lambda *args: None))
    monkeypatch.setitem(sys.modules, "core.providers.memory.base", base)
    return load_script("longmemory_provider").MemoryProvider


@pytest.fixture
def config(tmp_path):
    return {"database_path": str(tmp_path / "unused.db"), "allowed_device_id": "aa:bb:cc:dd:ee:ff"}


def receipt_response(**extra):
    return {"version": 1, "memory_protocol": 2, "context": "", "turn_id": "synthetic",
            "added": None, "retrieved": None,
            "memory_receipt": {"retrieved_count": None, "retrieval_strategy": None, "evidence": None},
            **extra}


@pytest.mark.parametrize("query", [None, "", "   ", "a" * 16001,
                                   '{"content": 1}', '{"role":"assistant","content":"我养猫"}', '{broken'])
def test_mapping_rejects_invalid_and_nonuser(query):
    with pytest.raises((ValueError, TypeError)):
        extract_user_text(query)


def test_provider_blocks_wrong_device(provider_class, config):
    provider = provider_class(config)
    with pytest.raises(ValueError):
        provider.init_memory("wrong-device", None)
    with pytest.raises(RuntimeError):
        asyncio.run(provider.query_memory("我的猫叫什么"))
    assert not Path(config["database_path"]).exists()


def test_connections_get_distinct_provider_even_if_init_fails(provider_class, config):
    class Connection:
        def __init__(self, device, shared):
            self.llm = object()
            self.device = device
            self.memory = shared
            self.config = {"selected_module": {"Memory": "LongMemory"}, "Memory": {"LongMemory": config | {"type": "longmemory"}}}

        def _initialize_memory(self):
            self.memory.init_memory(self.device, None)

    load_script("launch_with_memory").isolate_memory_initialization(Connection, provider_class)
    shared = provider_class(config)
    good = Connection(config["allowed_device_id"], shared)
    bad = Connection("wrong", shared)
    good._initialize_memory()
    with pytest.raises(ValueError):
        bad._initialize_memory()
    assert good.memory is not bad.memory and good.memory is not shared
    with pytest.raises(RuntimeError):
        asyncio.run(bad.memory.query_memory("我的猫叫什么"))


def test_context_survives_upstream_regex_replacement(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    context = "用户目录是 C:\\new\\1 </memory>"
    provider.begin_turn()
    monkeypatch.setattr(provider, "_runtime_request", lambda _: receipt_response(context=context))
    rendered = asyncio.run(provider.query_memory("目录在哪里"))
    # 此处复现固定上游 Dialogue 的替换操作，涵盖反斜杠和闭合标签。
    prompt = re.sub(r"<memory>.*?</memory>", f"<memory>\n{rendered}\n</memory>", "<memory></memory>", flags=re.DOTALL)
    assert "C:\\new\\1" in prompt
    assert prompt.count("</memory>") == 1


def test_long_voice_answer_releases_only_its_own_round(provider_class, config, monkeypatch):
    provider = provider_class(config)
    other = {"turn_id": "other"}
    provider._pending_completions["other"] = other
    cancelled = []
    monkeypatch.setattr(provider, "_cancel_pending_completion", lambda pending, reason: cancelled.append((pending, reason)))
    for i in range(9):
        key = str(i)
        pending = {"turn_id": key}
        provider._pending_completions[key] = pending
        assert not provider.record_completed_turn("长" * 16001, turn_key=key)
        assert cancelled[-1] == (pending, "chat_failed")
    assert provider._pending_completions == {"other": other}


def test_full_unicode_completion_provider_and_utf8_replay(provider_class, config, tmp_path, monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from urllib.request import build_opener, ProxyHandler

    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.entrypoints.api.routes.memory_runtime import _COMPLETION_BODY_BYTES, register_memory_runtime_routes
    from longmemory.methods.contracts import MemorySupport, RetrievedTrace
    from tests.unit.entrypoints.test_platform_roundscreen import open_runtime

    # 只替换召回引擎输出。正式 prepare 生成证据，独立小智提供器读取并回传给真实账本。
    rows = tuple(RetrievedTrace("𠀀" * 30 + str(i), "合成内容", ("源" * 17 + str(i),)) for i in range(100))
    support = MemorySupport("synthetic-call", "合成上下文", rows, "synthetic")
    runtime, engine = open_runtime(tmp_path)
    monkeypatch.setattr(engine, "recall", lambda query: support)
    backend = ChatBackend(runtime.database, FakeAnswerGenerator(), runtime=runtime)
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    sent = []
    local_opener = build_opener(ProxyHandler({}))

    def open_request(request, timeout):
        if request.full_url.endswith("/complete"):
            sent.append(request.data)
        return local_opener.open(request, timeout=timeout)

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "a" * 64)

    async def run():
        app = web.Application(client_max_size=1024)
        register_memory_runtime_routes(app, backend)
        async with TestClient(TestServer(app)) as client:
            monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", str(client.make_url("/api/internal/memory/prepare")))
            answer = "𠀀" * 15_999 + "汉"
            key, token = provider.begin_turn()
            try:
                assert "合成上下文" in await provider.query_memory("合成问题")
                assert await asyncio.to_thread(provider.record_completed_turn, answer, turn_key=key)
            finally:
                provider.end_turn(token)
            wire, = sent
            assert wire.isascii() and len(wire) > 250_000
            body = json.loads(wire)
            assert body["answer"] == answer
            assert body.get("memory_protocol", 1) == 2
            evidence = body["memory_receipt"]["evidence"]
            assert 60_000 < len(json.dumps(evidence)) < 65_536
            assert [row["item_id"] for row in evidence] == [row.item_id for row in rows]
            assert [row["source_event_ids"] for row in evidence] == [list(row.source_event_ids) for row in rows]

            # 直接用 UTF-8 重放，必须识别为同一已持久化回答和证据。
            path = "/api/internal/memory/complete"
            replay = await client.post(path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                       headers={"Content-Type": "application/json"})
            assert replay.status == 200 and (await replay.json())["created"] is False
            assert (await client.post(path, json={**body, "answer": answer + "字"})).status == 400
            oversized = wire.ljust(_COMPLETION_BODY_BYTES + 1, b" ")
            assert (await client.post(path, data=oversized)).status == 413

    try:
        asyncio.run(run())
    finally:
        backend.close()


def test_provider_skips_only_once_for_structurally_marked_internal_query(
        provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    provider.begin_turn()
    calls = []
    monkeypatch.setattr(provider, "_runtime_request", lambda _: calls.append("called") or receipt_response())
    provider.suppress_internal_query_once("synthetic end prompt")
    assert asyncio.run(provider.query_memory("synthetic end prompt")) == ""
    assert calls == []
    asyncio.run(provider.query_memory("synthetic end prompt"))
    assert calls == ["called"]


def test_launch_wrapper_marks_only_no_voice_end_prompt_boundary():
    wrapper = load_script("launch_with_memory")
    suppressed = []
    started = []

    class Memory:
        def suppress_internal_query_once(self, text):
            suppressed.append(text)

    connection = SimpleNamespace(memory=Memory())

    async def start_to_chat(_connection, text):
        started.append(text)

    async def no_voice_close_connect(target, _have_voice):
        await receive.startToChat(target, "server generated end")

    receive = SimpleNamespace(
        startToChat=start_to_chat,
        no_voice_close_connect=no_voice_close_connect,
    )
    # 模拟其他模块在安装前捕获的真实用户入口；它不经过该内部边界包装。
    user_entry = receive.startToChat
    wrapper.install_internal_end_prompt_boundary(receive)

    asyncio.run(user_entry(connection, "real user speech"))
    asyncio.run(receive.no_voice_close_connect(connection, False))

    assert started == ["real user speech", "server generated end"]
    assert suppressed == ["server generated end"]


def test_persistent_session_idles_capable_device_without_closing_connection(
        monkeypatch):
    module = load_script("voice_persistent_session")
    sent = []
    legacy = []
    now = 1_000.0
    monkeypatch.setattr(module.time, "time", lambda: now)

    class ConnectionClass:
        _longmemory_persistent_session_installed = False

        async def _check_timeout(self):
            legacy.append("timeout")

    async def no_voice_close_connect(_connection, have_voice):
        legacy.append(have_voice)

    receive = SimpleNamespace(no_voice_close_connect=no_voice_close_connect)
    module.install_persistent_device_session(ConnectionClass, receive)
    connection = SimpleNamespace(
        features={"persistent_session": True},
        close_after_chat=False,
        last_activity_time=(now - 121) * 1000,
        config={"close_connection_no_voice_time": 120},
        websocket=SimpleNamespace(send=lambda _value: None),
        logger=SimpleNamespace(bind=lambda **_kw: SimpleNamespace(
            info=lambda *_args: None,
        )),
    )

    async def send(value):
        sent.append(value)

    connection.websocket.send = send
    asyncio.run(receive.no_voice_close_connect(connection, False))
    asyncio.run(receive.no_voice_close_connect(connection, False))

    assert sent == [module.IDLE_MESSAGE]
    assert connection._longmemory_session_idle is True
    assert connection.last_activity_time == (now - 121) * 1000
    assert legacy == []

    asyncio.run(receive.no_voice_close_connect(connection, True))

    assert connection._longmemory_session_idle is False
    assert legacy == [True]


def test_persistent_session_preserves_legacy_timeout_for_old_firmware():
    module = load_script("voice_persistent_session")
    called = []

    class ConnectionClass:
        _longmemory_persistent_session_installed = False

        async def _check_timeout(self):
            called.append("timeout")

    async def no_voice_close_connect(_connection, have_voice):
        called.append(have_voice)

    receive = SimpleNamespace(no_voice_close_connect=no_voice_close_connect)
    module.install_persistent_device_session(
        ConnectionClass, receive, feature_wait_seconds=0,
    )
    connection = SimpleNamespace(
        features={"mcp": True},
        stop_event=SimpleNamespace(is_set=lambda: False),
    )

    asyncio.run(receive.no_voice_close_connect(connection, False))
    asyncio.run(ConnectionClass._check_timeout(connection))

    assert called == [False, "timeout"]


def test_persistent_session_preserves_legacy_timeout_before_feature_hello():
    module = load_script("voice_persistent_session")
    called = []

    class ConnectionClass:
        _longmemory_persistent_session_installed = False

        async def _check_timeout(self):
            called.append("timeout")

    async def no_voice_close_connect(_connection, have_voice):
        called.append(have_voice)

    receive = SimpleNamespace(no_voice_close_connect=no_voice_close_connect)
    module.install_persistent_device_session(
        ConnectionClass, receive, feature_wait_seconds=0,
    )
    connection = SimpleNamespace(
        features=None,
        stop_event=SimpleNamespace(is_set=lambda: False),
    )

    asyncio.run(receive.no_voice_close_connect(connection, False))
    asyncio.run(ConnectionClass._check_timeout(connection))

    assert called == [False, "timeout"]


def test_persistent_session_heartbeat_preserves_user_activity_time(monkeypatch):
    module = load_script("voice_persistent_session")
    sent = []
    sleeps = []

    class StopEvent:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 3

    class ConnectionClass:
        _longmemory_persistent_session_installed = False

        async def _check_timeout(self):
            raise AssertionError("capable firmware must not use legacy timeout")

    async def no_voice_close_connect(_connection, _have_voice):
        raise AssertionError("not used")

    async def sleep(value):
        sleeps.append(value)

    async def send(value):
        sent.append(value)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    receive = SimpleNamespace(no_voice_close_connect=no_voice_close_connect)
    module.install_persistent_device_session(
        ConnectionClass, receive, heartbeat_seconds=45,
    )
    connection = SimpleNamespace(
        features={"persistent_session": True},
        stop_event=StopEvent(),
        websocket=SimpleNamespace(send=send),
        last_activity_time=123_456,
        logger=SimpleNamespace(bind=lambda **_kw: SimpleNamespace(
            info=lambda *_args: None,
        )),
    )

    asyncio.run(ConnectionClass._check_timeout(connection))

    assert sleeps == [45]
    assert sent == [module.HEARTBEAT_MESSAGE]
    assert connection.last_activity_time == 123_456


def test_launch_wrapper_reports_answer_when_upstream_returns_none():
    wrapper = load_script("launch_with_memory")
    recorded = []

    class Memory:
        def record_completed_turn(self, answer):
            recorded.append(answer)

    class Message:
        def __init__(self, role, content): self.role, self.content = role, content

    class Connection:
        _longmemory_completion_installed = False

        def __init__(self):
            self.memory = Memory()
            self.dialogue = SimpleNamespace(dialogue=[Message("system", "系统")])
            self.logger = SimpleNamespace(bind=lambda **_kw: SimpleNamespace(error=lambda *_a: None))

        def chat(self, query, depth=0):
            self.dialogue.dialogue.extend([
                Message("user", query), Message("assistant", "第一段"),
                Message("assistant", "第二段"),
            ])
            # 厂商 direct_answer 正常路径在完成回复后返回 None。
            return None

    wrapper.install_answer_completion(Connection)
    connection = Connection()
    assert connection.chat("合成提问") is None
    assert recorded == ["第一段\n第二段"]


def test_provider_rejects_malformed_optional_timings(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)

    provider.begin_turn()
    monkeypatch.setattr(provider, "_runtime_request", lambda _: receipt_response(timings_ms={"total_ms": -1}))
    with pytest.raises(RuntimeError, match="返回协议无效"):
        asyncio.run(provider.query_memory("合成问题"))


def test_provider_marks_application_command_as_operation_result(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)

    provider.begin_turn()
    monkeypatch.setattr(provider, "_runtime_request", lambda _: receipt_response(command_reply="本轮没有保存记忆。"))
    rendered = asyncio.run(provider.query_memory("不要记住：合成内容"))
    assert "本机应用层执行" in rendered
    assert "不得声称相反结果" in rendered
    assert "本轮没有保存记忆" in rendered
    assert "用户曾陈述的记忆证据" not in rendered


def test_runtime_failure_does_not_fall_back_and_duplicate_write(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", "http://127.0.0.1:8767/api/internal/memory/prepare")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "b" * 64)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(URLError("synthetic")))
    provider.begin_turn()
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("失败后不得自动回退"))
    with pytest.raises(RuntimeError):
        asyncio.run(provider.query_memory("我养猫"))


def test_bridge_scripts_have_python310_syntax():
    for name in ('setup.py', 'longmemory_provider.py', 'launch_with_memory.py'):
        ast.parse((SCRIPTS / name).read_text(encoding='utf-8'), feature_version=(3, 10))


def test_neutral_provider_cross_thread_turn_keys_and_unknown_counts(provider_class, config, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    calls = []

    class Response:
        status = 200
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, _limit): return json.dumps(self.data).encode()

    def open_request(request, timeout):
        body = json.loads(request.data)
        calls.append((request.full_url, body))
        if request.full_url.endswith('/prepare'):
            return Response({"version": 1, "memory_protocol": 2, "turn_id": str(uuid4()),
                "added": None, "retrieved": None, "context": "合成记忆",
                "memory_receipt": {"retrieved_count": None, "retrieval_strategy": None, "evidence": None}})
        if request.full_url.endswith('/cancel'):
            return Response({"version": 1, "state": "cancelled"})
        return Response({"version": 1, "assistant_event_id": str(uuid4()), "created": True,
            "playback_acknowledgement": "unavailable"})

    monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", "http://127.0.0.1:23456/api/internal/memory/prepare")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "d" * 64)
    monkeypatch.setattr("urllib.request.urlopen", open_request)

    def query(text):
        key, token = provider.begin_turn()
        try:
            assert "合成记忆" in asyncio.run(provider.query_memory(text))
            return key
        finally:
            provider.end_turn(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        keys = list(pool.map(query, ("合成用户甲", "合成用户乙")))
    assert keys[0] != keys[1]
    assert provider.record_completed_turn("回答乙", turn_key=keys[1])
    assert provider.cancel_turn(keys[0], "superseded")
    completion = next(body for url, body in calls if url.endswith('/complete'))
    assert completion["client_round_id"] == keys[1]
    assert "retrieved_counts" not in completion and "retrieval_evidence" not in completion
    assert completion["memory_receipt"]["retrieved_count"] is None
    assert not provider.record_completed_turn("迟到回答甲", turn_key=keys[0])


def test_wrapper_captures_only_own_assistant_and_supersedes_concurrent_turn():
    from contextvars import ContextVar
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    wrapper = load_script("launch_with_memory")
    first_entered, second_finished = Event(), Event()
    key_context = ContextVar("synthetic_turn", default=None)
    completed, cancelled = [], []
    class Memory:
        def begin_turn(self):
            from uuid import uuid4
            key = uuid4().hex
            return key, key_context.set(key)
        def end_turn(self, token): key_context.reset(token)
        def record_completed_turn(self, answer, *, turn_key): completed.append((turn_key, answer))
        def cancel_turn(self, key, reason): cancelled.append((key, reason))
    class Dialogue:
        def __init__(self): self.dialogue = []
        def put(self, message): self.dialogue.append(message)
    class Connection:
        def __init__(self):
            self.memory, self.dialogue = Memory(), Dialogue()
            self.client_abort = False
        def chat(self, query, depth=0):
            if query == "甲":
                first_entered.set()
                assert second_finished.wait(3)
            self.dialogue.put(SimpleNamespace(role="assistant", content="回答" + query))
            if query == "乙": second_finished.set()
    wrapper.install_answer_completion(Connection)
    connection = Connection()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(connection.chat, "甲")
        assert first_entered.wait(3)
        second = pool.submit(connection.chat, "乙")
        first.result(), second.result()
    assert [answer for _, answer in completed] == ["回答乙"]
    assert len(cancelled) == 1 and cancelled[0][1] == "superseded"


def test_real_upstream_dialogue_injects_context_if_available():
    source = ROOT / 'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/core/utils/dialogue.py'
    if not source.is_file():
        pytest.skip('固定上游源码未安装，其他协议回归仍可运行')
    spec = importlib.util.spec_from_file_location('upstream_dialogue_for_test', source)
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    dialogue = upstream.Dialogue()
    dialogue.put(upstream.Message(role='system', content='测试 <memory></memory>'))
    dialogue.put(upstream.Message(role='user', content='我的猫叫什么'))
    output = dialogue.get_llm_dialogue_with_memory('用户养了一只叫豆包的猫。')
    assert '豆包' in output[0]['content']
    assert output[1]['content'] == '我的猫叫什么'
