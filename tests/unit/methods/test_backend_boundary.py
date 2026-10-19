"""目录引擎是契约替身，不是 Hy 实现或效果证据。所有正文为合成数据。"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from longmemory.bootstrap import assemble_backend, build_backend_runtime, build_legacy_runtime
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.entrypoints.api.method_management import LegacyMemoryAdministration
from longmemory.methods.backend_contracts import ManagementCapabilities, MemoryItem, MemoryPage, StateResource
from longmemory.methods.contracts import (
    MemoryEvent, MemorySupport, MethodCapabilities, ObservationResult,
    RetrievedTrace, UnsupportedCapabilityError,
)
from longmemory.methods.longmemory_v1.method import LongMemoryV1


NOW = datetime(2026, 10, 19, tzinfo=UTC)


class DirectoryEngine:
    name = "synthetic_directory"
    implementation_version = "test-1"
    capabilities = MethodCapabilities(source_trace=True, session_metadata=True, idempotent_observation=True)

    def __init__(self, path):
        self.path = path
        self.path.mkdir(exist_ok=True)
        self.file = path / "graph.json"
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {"nodes": {}, "events": []}
        self.closed = False
        self.fail = False
        self.fail_after_write = False

    def save(self):
        temporary = self.path / "graph.tmp"
        temporary.write_text(json.dumps(self.data), encoding="utf-8")
        temporary.replace(self.file)

    def observe(self, event):
        assert not self.closed
        assert event.role == "user", "助手不应进入用户事实引擎"
        if self.fail:
            raise RuntimeError("synthetic_secret_not_for_api")
        if event.event_id not in self.data["events"]:
            self.data["events"].append(event.event_id)
            self.data["nodes"][event.event_id] = {"content": event.content, "source": event.event_id, "revision": 1}
            self.save()
        if self.fail_after_write:
            raise RuntimeError("模拟提交后回执失败")
        # 未提供内部写入过程是合法的，不能强迫伪造 AtomicMemory。
        return ObservationResult(event.event_id, None)

    def recall(self, query):
        assert not self.closed
        items = tuple(RetrievedTrace(key, row["content"], (row["source"],)) for key, row in self.data["nodes"].items())
        return MemorySupport("directory-call", "\n".join(item.content for item in items), items, "graph_native")

    def archive(self, event):
        raise AssertionError("平台不依赖外部引擎的 archive")

    def wait_until_ready(self):
        assert not self.closed

    def close(self):
        self.closed = True


class DirectoryAdministration:
    capabilities = ManagementCapabilities(listing=True, detail=True, correction=True, deletion=True)

    def __init__(self, engine):
        self.engine = engine

    def get_item(self, item_id):
        try:
            row = self.engine.data["nodes"][item_id]
        except KeyError:
            raise LookupError("not_found") from None
        return MemoryItem(item_id, row["content"], str(row["revision"]), "graph_node", (row["source"],), NOW, state="active")

    def list_items(self, *, query="", state="active", limit=25, offset=0):
        if state not in {"all", "active"}:
            raise UnsupportedCapabilityError("graph_state_unsupported")
        items = tuple(self.get_item(key) for key in self.engine.data["nodes"] if query in self.engine.data["nodes"][key]["content"])
        return MemoryPage(items[offset:offset+limit], len(items), offset, limit)

    def correct_item(self, item_id, content, *, expected_revision, source):
        item = self.get_item(item_id)
        if item.revision != expected_revision:
            raise ValueError("changed")
        self.engine.data["nodes"][item_id] = {"content": content, "source": source.event_id, "revision": int(item.revision)+1}
        self.engine.save()
        return self.get_item(item_id)

    def delete_item(self, item_id, *, expected_revision):
        if self.get_item(item_id).revision != expected_revision:
            raise ValueError("changed")
        del self.engine.data["nodes"][item_id]
        self.engine.save()


def directory_runtime(root, *, create=True, management=True, idempotent=True):
    engine = DirectoryEngine(root / "native-state")
    if not idempotent:
        engine.capabilities = replace(engine.capabilities, idempotent_observation=False)
    assembly = assemble_backend(method=engine, resources=(StateResource("native", engine.path, "directory"),),
        source_path=root / "sources.sqlite3", create_sources=create,
        management=DirectoryAdministration(engine) if management else None)
    return build_backend_runtime(assembly, clock=lambda: NOW), engine


@pytest.mark.parametrize("kind", ["legacy", "directory"])
def test_unified_runtime_management_and_reopen(tmp_path, kind):
    def open_runtime(create):
        if kind == "directory":
            return directory_runtime(tmp_path, create=create)[0]
        path = tmp_path / "legacy.db"
        method = LongMemoryV1(path, allow_cross_thread=True)
        return build_legacy_runtime(path, method=method, clock=lambda: NOW,
            management=LegacyMemoryAdministration(MemoryBackend(path, allow_delete=True, allow_correction=True)))
    runtime = open_runtime(True)
    try:
        turn = runtime.prepare_user("我养了一只叫豆包的猫")
        assert turn.support.context
        page = runtime.administer("listing", "list_items")
        assert page.total == 1
        item = runtime.administer("detail", "get_item", page.items[0].item_id)
        assert runtime.source_detail(item.source_event_ids[0])["role"] == "user"
        source = MemoryEvent("correction-source", "user", "用户的猫叫年糕。", NOW)
        corrected = runtime.administer("correction", "correct_item", item.item_id, source.content,
            expected_revision=item.revision, source=source)
        assert corrected.source_event_ids == (source.event_id,)
        assert runtime.source_detail(source.event_id)["content"] == source.content
        assistant = runtime.record_assistant("用户的猫叫错误名字。")
        assert runtime.source_detail(assistant.event_id)["role"] == "assistant"
    finally:
        runtime.close()
    runtime = open_runtime(False)
    try:
        assert "年糕" in runtime._method.recall("猫叫什么").context
        current = runtime.administer("detail", "get_item", corrected.item_id)
        runtime.administer("deletion", "delete_item", current.item_id, expected_revision=current.revision)
        assert runtime.source_detail(source.event_id)["content"] == source.content
        assert runtime.administer("listing", "list_items").total == 0
    finally:
        runtime.close()


def test_directory_roles_metadata_read_only_and_isolation(tmp_path):
    runtime, engine = directory_runtime(tmp_path)
    try:
        event = MemoryEvent("source-one", "user", "合成研究方向", NOW, "synthetic-session")
        runtime._method.observe(event)
        runtime._method.observe(event)
        assert engine.data["events"] == [event.event_id]
        assert runtime.source_detail(event.event_id)["session_id"] == "synthetic-session"
        before = engine.file.read_bytes(), (tmp_path / "sources.sqlite3").read_bytes()
        runtime._method.recall("研究")
        assert before == (engine.file.read_bytes(), (tmp_path / "sources.sqlite3").read_bytes())
        runtime.configure(write_enabled=False, use_enabled=False)
        turn = runtime.prepare_user("仅归档合成消息")
        assert not turn.support.context
        assert runtime.source_status(turn.event.event_id)["state"] == "archived"
        assert engine.data["events"] == [event.event_id]
        with pytest.raises(ValueError, match="memory_write_paused"):
            runtime.retry_source(turn.event.event_id, expected_attempt_id="none")
        with pytest.raises(ValueError, match="source_event_conflict"):
            runtime._method.observe(replace(event, content="同 ID 不同内容"))
        assert not runtime.status()["scenario_available"]
        assert not runtime.status()["persona_available"]
        with pytest.raises(ValueError, match="scenario_memory_unavailable"):
            runtime.configure(write_enabled=True, use_enabled=True, scenario_use_enabled=True)
    finally:
        runtime.close()
    other = tmp_path / "other"
    other.mkdir()
    isolated, _ = directory_runtime(other)
    try:
        assert isolated.administer("listing", "list_items").total == 0
    finally:
        isolated.close()


@pytest.mark.parametrize("text", ["不是豆包，而是年糕", "我以前住北京，但现在住上海", "请删除猫的名字", "确认删除", "你为什么知道猫的名字", "请记住：用户有猫"])
def test_unsupported_natural_operations_do_not_write_engine(tmp_path, text):
    runtime, engine = directory_runtime(tmp_path)
    try:
        turn = runtime.prepare_user(text)
        assert turn.memory_command.status == "unsupported"
        assert runtime.source_detail(turn.event.event_id)["content"] == text
        assert engine.data["events"] == []
    finally:
        runtime.close()


@pytest.mark.parametrize("management", [False, True])
def test_unsupported_capabilities_do_not_fallback(tmp_path, management):
    runtime, engine = directory_runtime(tmp_path, management=management)
    try:
        if not management:
            with pytest.raises(UnsupportedCapabilityError):
                runtime.administer("listing", "list_items")
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer("personas", "get_persona")
        if management:
            with pytest.raises(ValueError, match="management_operation_invalid"):
                runtime.administer("detail", "delete_item", "missing")
    finally:
        runtime.close()


@pytest.mark.parametrize("after_write", [False, True])
def test_failed_pipeline_explicit_retry_persists_once(tmp_path, after_write):
    runtime, engine = directory_runtime(tmp_path)
    try:
        engine.fail, engine.fail_after_write = not after_write, after_write
        turn = runtime.prepare_user("合成事实")
        assert turn.observation.processing_status == "source_only"
        status = runtime.source_status(turn.event.event_id)
        assert status["state"] == "failed"
        assert "secret" not in json.dumps(status)
        engine.fail = engine.fail_after_write = False
        result = runtime.retry_source(turn.event.event_id, expected_attempt_id=status["attempt_id"])
        assert result.processing_status == "completed"
        assert engine.data["events"] == [turn.event.event_id]
        with pytest.raises(ValueError, match="source_retry_changed"):
            runtime.retry_source(turn.event.event_id, expected_attempt_id=status["attempt_id"])
    finally:
        runtime.close()


def test_crash_window_is_uncertain_and_idempotency_required(tmp_path):
    runtime, engine = directory_runtime(tmp_path)
    event = MemoryEvent("crashed", "user", "崩溃合成事实", NOW)
    runtime._method.archive(event)
    attempt = runtime._method.journal.begin(event.event_id)
    engine.observe(event)  # 提交成功但平台尚未得到回执。
    runtime.close()
    runtime, engine = directory_runtime(tmp_path, create=False, idempotent=False)
    try:
        assert runtime.source_status(event.event_id)["state"] == "uncertain"
        with pytest.raises(UnsupportedCapabilityError):
            runtime.retry_source(event.event_id, expected_attempt_id=attempt)
    finally:
        runtime.close()
    runtime, engine = directory_runtime(tmp_path, create=False)
    try:
        runtime.retry_source(event.event_id, expected_attempt_id=attempt)
        assert engine.data["events"] == [event.event_id]
    finally:
        runtime.close()


def test_deferred_raw_first_survives_restart_without_auto_replay(tmp_path):
    runtime, engine = directory_runtime(tmp_path, idempotent=False)
    turn = runtime.prepare_user("延后合成事实", defer_slow_observation=True)
    assert not engine.data["events"]
    assert runtime.source_status(turn.event.event_id)["state"] == "pending"
    runtime.close()
    runtime, engine = directory_runtime(tmp_path, create=False, idempotent=False)
    try:
        status = runtime.source_status(turn.event.event_id)
        assert not engine.data["events"]
        runtime.retry_source(turn.event.event_id, expected_attempt_id=status["attempt_id"])
        assert engine.data["events"] == [turn.event.event_id]
        completed = runtime.prepare_user("正常延后合成事实", defer_slow_observation=True)
        assert runtime.complete_deferred_observation(completed.event.event_id)
        assert not runtime.complete_deferred_observation(completed.event.event_id)
        runtime.wait_for_deferred_observations()
        assert runtime.source_status(completed.event.event_id)["state"] == "completed"
    finally:
        runtime.close()


def test_concurrent_runtime_and_compare_and_swap(tmp_path):
    runtime, engine = directory_runtime(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            turns = list(pool.map(runtime.prepare_user, [f"合成事实 {number}" for number in range(12)]))
        assert len(engine.data["events"]) == 12
        item = runtime.administer("listing", "list_items").items[0]
        def correct(number):
            try:
                return runtime.administer("correction", "correct_item", item.item_id, f"纠正 {number}",
                    expected_revision=item.revision, source=MemoryEvent(f"correction-{number}", "user", f"纠正 {number}", NOW))
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(value is not None for value in pool.map(correct, range(2))) == 1
    finally:
        runtime.close()
    runtime.close()
    with pytest.raises(RuntimeError):
        runtime.prepare_user("关闭后拒绝")


def test_source_journal_exclusive_owner_and_no_overwrite(tmp_path):
    runtime, _ = directory_runtime(tmp_path)
    try:
        with pytest.raises((OSError, BlockingIOError)):
            directory_runtime(tmp_path, create=False)
        before = (tmp_path / "sources.sqlite3").read_bytes()
        with pytest.raises(FileExistsError):
            directory_runtime(tmp_path, create=True)
        assert before == (tmp_path / "sources.sqlite3").read_bytes()
    finally:
        runtime.close()


@pytest.mark.parametrize("writes_allowed", [False, True])
def test_neutral_http_management_chat_and_legacy_rejection(tmp_path, writes_allowed):
    import asyncio
    import socket
    from aiohttp import ClientSession, CookieJar, web
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.entrypoints.api.server import create_app

    class Bridge:
        async def close(self):
            pass

    async def run():
        runtime, engine = directory_runtime(tmp_path)
        chat = ChatBackend(tmp_path / "sources.sqlite3", FakeAnswerGenerator(), runtime=runtime)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert port not in {8767, 8000, 8003}
        base = f"http://127.0.0.1:{port}"
        app = create_app(port=port, bridge=Bridge(), chat_backend=chat,
                         memory_runtime=runtime, database=tmp_path / "sources.sqlite3",
                         allow_memory_correction=writes_allowed, allow_memory_delete=writes_allowed,
                         observability_root=tmp_path)
        runner = web.AppRunner(app, access_log=None)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
                assert (await client.get(base + "/api/memory-engine")).status == 401
                csrf = await (await client.get(base + "/api/session", headers={"X-Console-Bootstrap": "1"})).json()
                headers = {"Origin": base, "X-Console-CSRF": csrf["csrf"]}
                state = await (await client.get(base + "/api/memory-engine")).json()
                assert state["state_resources"][0]["kind"] == "directory"
                config = await (await client.get(base + "/api/memory-config")).json()
                assert config["representation"] == "method_defined" and not config["allow_clear"]
                for path in ("/api/memories", "/api/personas", "/api/scenarios", "/api/proactive-policy"):
                    response = await client.get(base + path)
                    assert response.status == 501, (path, await response.text())
                # 真实聊天后端可消费 writes=None，助手只进入平台来源库。
                turn = await asyncio.to_thread(chat.run, "我养了一只叫豆包的猫", ())
                assert turn["status"] == "completed", turn
                assert turn["writes"] is None and turn["assistant_saved"]
                assert len(engine.data["events"]) == 1
                page = await (await client.get(base + "/api/memory-engine/items")).json()
                item = page["items"][0]
                assert item["kind"] == "graph_node" and "subject_id" not in item
                source = await (await client.get(base + "/api/memory-engine/sources/" + item["source_event_ids"][0])).json()
                assert source["role"] == "user" and source["state"] == "completed"
                url = base + "/api/memory-engine/items/" + item["item_id"]
                response = await client.post(url + "/corrections", headers=headers,
                    json={"content": "猫叫年糕", "revision": item["revision"]})
                assert response.status == (200 if writes_allowed else 403)
                if writes_allowed:
                    corrected = await response.json()
                    assert corrected["content"] == "猫叫年糕"
                    assert (await client.delete(url, json={"revision": corrected["revision"]})).status == 403
                    assert (await client.delete(url, json={"revision": item["revision"]}, headers=headers)).status == 409
                    assert (await client.delete(url, json={"revision": corrected["revision"]}, headers=headers)).status == 200
                    assert runtime.source_detail(corrected["source_event_ids"][0])["content"] == "猫叫年糕"
                else:
                    assert (await client.delete(url, json={"revision": item["revision"]}, headers=headers)).status == 403
                assert (await client.get(base + "/api/memory-engine/items?limit=999")).status == 400
                assert (await client.post(url + "/corrections", json={"content": "x", "revision": "1", "path": "forbidden"}, headers=headers)).status == (400 if writes_allowed else 403)
        finally:
            await runner.cleanup()
            chat.close()
            sock.close()
    asyncio.run(run())


def test_invalid_assembly_never_opens_overlapping_source(tmp_path):
    engine = DirectoryEngine(tmp_path / "native-state")
    with pytest.raises(ValueError, match="overlap"):
        assemble_backend(method=engine, resources=(StateResource("native", engine.path, "directory"),),
            source_path=engine.path / "sources.sqlite3", create_sources=True)
    assert not (engine.path / "sources.sqlite3").exists()
    assert engine.closed


def test_journal_is_bound_to_exact_engine_resource_identity(tmp_path):
    runtime, _ = directory_runtime(tmp_path)
    runtime.close()
    wrong = DirectoryEngine(tmp_path / "different-state")
    with pytest.raises(ValueError, match="source_journal_engine_mismatch"):
        assemble_backend(method=wrong, resources=(StateResource("native", wrong.path, "directory"),),
                         source_path=tmp_path / "sources.sqlite3")
    assert wrong.closed


def test_session_support_is_enforced_and_unknown_retrieval_stays_unknown(tmp_path):
    runtime, engine = directory_runtime(tmp_path)
    try:
        engine.capabilities = replace(engine.capabilities, session_metadata=False)
        event = MemoryEvent("session-source", "user", "合成会话", NOW, "session")
        result = runtime._method.observe(event)
        assert result.warning_code == "engine_session_metadata_unsupported"
        assert not engine.data["events"]
        assert runtime.source_detail(event.event_id)["session_id"] == "session"
        from longmemory.adapters.llm.fake import FakeAnswerGenerator
        from longmemory.entrypoints.api.chat_backend import ChatBackend
        engine.recall = lambda query: MemorySupport("unknown-trace", "合成上下文", None)
        chat = ChatBackend(tmp_path / "sources.sqlite3", FakeAnswerGenerator(), runtime=runtime)
        turn = chat.run("合成测试", ())
        assert turn["status"] == "completed" and turn["retrieved"] is None
    finally:
        runtime.close()


@pytest.mark.parametrize("text", ["", "  "])
def test_empty_input_is_rejected_before_archival(tmp_path, text):
    runtime, engine = directory_runtime(tmp_path)
    try:
        with pytest.raises(ValueError):
            runtime.prepare_user(text)
        assert runtime._method.journal.events() == ()
        assert not engine.data["events"]
    finally:
        runtime.close()
