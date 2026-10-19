"""新后端圆屏闭环：仅合成库，无模型网络、日用服务或真实设备。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import pytest

from longmemory.bootstrap import assemble_backend, build_backend_runtime
from longmemory.application.round_screen_turns import memory_receipt
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.methods.backend_contracts import StateResource
from longmemory.methods.contracts import MethodCapabilities, MemorySupport, ObservationResult, RetrievedTrace


class Engine:
    name = "synthetic_roundscreen"
    implementation_version = "1"
    capabilities = MethodCapabilities(session_metadata=True)

    def __init__(self, directory):
        self.file = directory / "engine.json"
        self.data = json.loads(self.file.read_text()) if self.file.exists() else {}
        self.fail = False
        self.calls = []

    def observe(self, event):
        assert event.role == "user"
        self.calls.append(event)
        if self.fail:
            raise RuntimeError("synthetic sensitive detail")
        self.data[event.event_id] = event.content
        self.file.write_text(json.dumps(self.data))
        return ObservationResult(event.event_id, None)

    def recall(self, query):
        return MemorySupport("synthetic-call", "\n".join(self.data.values()), tuple(
            RetrievedTrace(key, value, (key,)) for key, value in self.data.items()), "native_test")

    def wait_until_ready(self): pass
    def close(self): pass


def open_runtime(directory, *, create=True, clock=None):
    engine = Engine(directory)
    assembly = assemble_backend(method=engine, resources=(StateResource("test_state", directory / "engine.json", "file"),),
        source_path=directory / "sources.db", create_sources=create)
    return build_backend_runtime(assembly, clock=clock), engine


def prepare(runtime, *, text="我喜欢合成蓝莓茶", session="a" * 32, round_id=None):
    return runtime.prepare_round_screen(text, client_round_id=round_id or uuid4().hex,
        session_id=session, request_id="b" * 24)[0]


def complete(runtime, turn, answer="我记下你的表达了。", **kwargs):
    return runtime.complete_round_screen(turn_id=turn.event.event_id, answer=answer,
        receipt=memory_receipt(turn), request_id="c" * 24, **kwargs)


def test_fact_becomes_recallable_only_after_completion_and_assistant_is_archive_only(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    try:
        turn = prepare(runtime)
        assert turn.support.retrieved == () and engine.calls == []
        assert runtime.source_status(turn.event.event_id)["state"] == "pending"
        result = complete(runtime, turn, "助手建议：明天喝红茶。")
        runtime.wait_for_deferred_observations()
        assert runtime.source_status(turn.event.event_id)["state"] == "completed"
        assert len(engine.calls) == 1
        assert runtime.source_detail(result.assistant_message_id)["role"] == "assistant"
        assert runtime.source_detail(result.assistant_message_id)["session_id"] == "a" * 32
        second = prepare(runtime, text="我喜欢什么？")
        assert "蓝莓茶" in second.support.context and "红茶" not in second.support.context
        assert runtime.round_screen_status(turn.event.event_id)["complete_request_id"] == "c" * 24
    finally:
        runtime.close()


def test_duplicate_and_conflicting_completion_are_persistent(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    turn = prepare(runtime, round_id="d" * 32)
    with pytest.raises(ValueError, match="prepare_already_recorded"):
        prepare(runtime, round_id="d" * 32)
    first = complete(runtime, turn)
    assert not complete(runtime, turn).created
    runtime.wait_for_deferred_observations()
    runtime.close()
    runtime, engine = open_runtime(tmp_path, create=False)
    try:
        assert complete(runtime, turn).assistant_message_id == first.assistant_message_id
        assert not complete(runtime, turn).created
        with pytest.raises(ValueError, match="turn_conflict"):
            complete(runtime, turn, answer="另一个答案")
        assert engine.calls == []
    finally:
        runtime.close()


def test_pending_survives_restart_and_only_explicit_completion_dispatches(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    turn = prepare(runtime)
    runtime.close()
    runtime, engine = open_runtime(tmp_path, create=False)
    try:
        assert not engine.calls
        complete(runtime, turn)
        runtime.wait_for_deferred_observations()
        assert len(engine.calls) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("reason", ["cancelled", "superseded", "chat_failed"])
def test_cancelled_round_never_accepts_late_completion(tmp_path, reason):
    runtime, engine = open_runtime(tmp_path)
    try:
        turn = prepare(runtime)
        assert runtime.cancel_round_screen(turn.event.event_id, reason=reason)["state"] == "cancelled"
        with pytest.raises(ValueError, match="turn_cancelled"):
            complete(runtime, turn)
        assert runtime.source_status(turn.event.event_id)["state"] == "pending"
        assert not engine.calls
    finally:
        runtime.close()


def test_timeout_wrong_round_and_tampered_receipt_cannot_archive_assistant(tmp_path):
    now = [datetime(2026, 10, 19, tzinfo=UTC)]
    runtime, engine = open_runtime(tmp_path, clock=lambda: now[0])
    try:
        turn = prepare(runtime, round_id="d" * 32)
        with pytest.raises(ValueError, match="round_mismatch"):
            complete(runtime, turn, client_round_id="e" * 32)
        with pytest.raises(ValueError, match="receipt_invalid"):
            runtime.complete_round_screen(turn_id=turn.event.event_id, answer="synthetic", receipt={})
        now[0] += timedelta(minutes=6)
        with pytest.raises(ValueError, match="timed_out"):
            complete(runtime, turn)
        assert runtime.round_screen_status(turn.event.event_id)["state"] == "timed_out"
        assert not engine.calls
    finally:
        runtime.close()


def test_failure_never_blind_retries_and_is_visible_after_restart(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    engine.fail = True
    turn = prepare(runtime)
    complete(runtime, turn)
    runtime.wait_for_deferred_observations()
    assert runtime.source_status(turn.event.event_id)["state"] == "failed"
    complete(runtime, turn)
    runtime.close()
    runtime, engine = open_runtime(tmp_path, create=False)
    try:
        complete(runtime, turn)
        assert not engine.calls
        status = runtime.source_status(turn.event.event_id)
        with pytest.raises(ValueError, match="idempotency"):
            runtime.retry_source(turn.event.event_id, expected_attempt_id=status["attempt_id"])
    finally:
        runtime.close()


def test_feedback_is_same_session_and_does_not_train_engine(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    try:
        first = prepare(runtime)
        complete(runtime, first)
        runtime.wait_for_deferred_observations()
        _, foreign = runtime.prepare_round_screen("你刚才记错了", client_round_id=uuid4().hex,
            session_id="f" * 32)
        assert foreign["recorded"] is False
        _, own = runtime.prepare_round_screen("你刚才记错了", client_round_id=uuid4().hex,
            session_id="a" * 32)
        assert own["target_user_message_id"] == first.event.event_id
        assert len(engine.calls) == 1
    finally:
        runtime.close()


def test_concurrent_completions_keep_assistant_sources_separate(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    try:
        turns = [prepare(runtime, text=f"合成事实{i}") for i in range(6)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda turn: complete(runtime, turn), turns))
        runtime.wait_for_deferred_observations()
        assert len({result.assistant_message_id for result in results}) == 6
        assert {call.event_id for call in engine.calls} == {turn.event.event_id for turn in turns}
    finally:
        runtime.close()


def test_web_and_roundscreen_share_memory_but_preserve_sidecars_and_sessions(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    backend = ChatBackend(runtime.database, FakeAnswerGenerator(), runtime=runtime, sidecar_database=tmp_path / "original.db")
    try:
        web = backend.run("我喜欢合成蓝莓茶", (), session_id="web:synthetic-chat")
        assert web["status"] == "completed"
        turn = prepare(runtime, text="我喜欢什么")
        assert "蓝莓茶" in turn.support.context
        assert engine.calls[0].session_id == "web:synthetic-chat"
        assert backend.roles.path == tmp_path / "original.db.role.sqlite3"
        assert backend.sidecar_database != runtime.database
    finally:
        backend.close()


def test_crash_during_prepare_is_uncertain_without_automatic_replay(tmp_path):
    runtime, engine = open_runtime(tmp_path)
    event_id = runtime._round_screen_store.reserve(client_round_id="d" * 32, session_id="a" * 32, request_id=None)
    runtime.close()
    runtime, engine = open_runtime(tmp_path, create=False)
    try:
        assert runtime.round_screen_status(event_id)["state"] == "uncertain"
        assert not engine.calls
    finally:
        runtime.close()


def test_platform_metadata_columns_upgrade_preserves_existing_source_and_completion(tmp_path):
    import sqlite3
    runtime, engine = open_runtime(tmp_path)
    turn = prepare(runtime)
    result = complete(runtime, turn)
    runtime.wait_for_deferred_observations()
    runtime.close()
    with sqlite3.connect(tmp_path / "sources.db") as connection:
        connection.execute("ALTER TABLE platform_rounds DROP COLUMN voice_round_id")
        connection.execute("ALTER TABLE platform_rounds DROP COLUMN cancel_request_id")
        connection.execute("UPDATE platform_rounds SET completion=? WHERE event_id=?",
            (json.dumps({"answer": "我记下你的表达了。", "receipt": memory_receipt(turn)}, sort_keys=True), turn.event.event_id))
    runtime, engine = open_runtime(tmp_path, create=False)
    try:
        assert runtime.source_detail(turn.event.event_id)["content"] == "我喜欢合成蓝莓茶"
        assert runtime.round_screen_status(turn.event.event_id)["voice_round_id"] is None
        assert complete(runtime, turn).assistant_message_id == result.assistant_message_id
        assert not engine.calls
    finally:
        runtime.close()


def test_real_http_neutral_prepare_completion_cancel_and_authentication(tmp_path):
    import asyncio
    import socket
    from aiohttp import ClientSession, web
    from longmemory.entrypoints.api.server import create_app

    class Bridge:
        async def close(self): pass

    async def run():
        runtime, engine = open_runtime(tmp_path)
        backend = ChatBackend(runtime.database, FakeAnswerGenerator(), runtime=runtime)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert port not in {8767, 8000, 8003, 8766, 8768}
        base = f"http://127.0.0.1:{port}"
        app = create_app(port=port, database=runtime.database, chat_backend=backend,
            memory_runtime=runtime, memory_runtime_token="d" * 64, bridge=Bridge(), observability_root=tmp_path)
        runner = web.AppRunner(app, access_log=None)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            headers = {"Authorization": "Bearer " + "d" * 64, "X-Voice-Round-Id": "b" * 24}
            async with ClientSession() as client:
                url = base + "/api/internal/memory/prepare"
                body = {"version": 1, "query": "我喜欢合成蓝莓茶", "client_round_id": "e" * 32, "session_id": "a" * 32}
                assert (await client.post(url, json=body)).status == 401
                result = await client.post(url, json=body, headers=headers)
                assert result.status == 200, await result.text()
                prepared = await result.json()
                assert prepared["memory_protocol"] == 2
                assert "retrieval_evidence" not in prepared and "scenario_retrieved" not in prepared
                assert prepared["memory_receipt"]["retrieved_count"] == 0
                assert runtime.round_screen_status(prepared["turn_id"])["voice_round_id"] == "b" * 24
                assert (await client.post(url, json=body, headers=headers)).status == 409
                completion = {"version": 1, "memory_protocol": 2, "turn_id": prepared["turn_id"],
                    "answer": "合成助手回答", "client_round_id": "e" * 32, "memory_receipt": prepared["memory_receipt"]}
                response = await client.post(base + "/api/internal/memory/complete", json=completion, headers=headers)
                assert response.status == 200, await response.text()
                assert (await response.json())["created"] is True
                response = await client.post(base + "/api/internal/memory/complete", json=completion, headers=headers)
                assert (await response.json())["created"] is False
                await asyncio.to_thread(runtime.wait_for_deferred_observations)
                assert len(engine.calls) == 1
                second = await (await client.post(url, json={**body, "client_round_id": "f" * 32}, headers=headers)).json()
                assert "蓝莓茶" in second["context"]
                cancellation = {"version": 1, "turn_id": second["turn_id"], "client_round_id": "f" * 32, "reason": "superseded"}
                response = await client.post(base + "/api/internal/memory/cancel", json=cancellation, headers=headers)
                assert (await response.json())["state"] == "cancelled"
                assert runtime.round_screen_status(second["turn_id"])["cancel_request_id"] is not None
                assert runtime.status()["proactive"]["state"] == "paused_backend_unsupported"
        finally:
            await runner.cleanup()
            backend.close()
            sock.close()
    asyncio.run(run())


def test_formal_server_selects_hy_sources_and_preserves_original_sidecar_base(tmp_path, monkeypatch):
    import sys
    from longmemory.entrypoints.api import server
    from longmemory.infrastructure.config import hy_deployment
    runtime, engine = open_runtime(tmp_path)
    original = tmp_path / "original-personal.db"
    from types import SimpleNamespace
    from longmemory.infrastructure.config.settings import ModelSettings
    runtime.attach_model_service(SimpleNamespace(model_settings=lambda phase: ModelSettings(),
        status=lambda: {"state": "available"}, pause_notice=lambda: None, close=lambda: None))
    original.write_bytes(b"synthetic-original-do-not-open")
    before = original.read_bytes()
    selected = {}
    monkeypatch.setattr(hy_deployment, "build_daily_hy_runtime", lambda root: runtime)
    monkeypatch.setattr(server.MemoryBackend, "list_page", lambda *args, **kwargs: pytest.fail("Hy startup must not read legacy database"))
    monkeypatch.setattr(server, "create_app", lambda **kwargs: selected.update(kwargs) or "synthetic-app")
    monkeypatch.setattr(server.web, "run_app", lambda app, **kwargs: None)
    monkeypatch.delenv("LONGMEMORY_RUNTIME_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["longmemory-api", "--enable-chat", "--chat-provider", "fake",
        "--memory-backend", "hy_memory", "--database", str(original), "--disable-proactive-schedule"])
    server.main()
    backend = selected["chat_backend"]
    assert selected["database"] == runtime.database
    assert backend.sidecar_database == original
    assert backend.roles.path == tmp_path / "original-personal.db.role.sqlite3"
    assert original.read_bytes() == before


def test_budget_pause_archives_user_and_returns_local_notice_without_engine_calls(tmp_path):
    from types import SimpleNamespace
    runtime, engine = open_runtime(tmp_path)
    runtime.attach_model_service(SimpleNamespace(status=lambda:{"state":"paused","reason":"budget_price_expired"},
        pause_notice=lambda:"共享预算暂停，原话已保留。", close=lambda:None))
    backend = ChatBackend(runtime.database, FakeAnswerGenerator(), runtime=runtime)
    try:
        turn = prepare(runtime)
        assert turn.observation.warning_code == "external_model_budget_paused"
        assert turn.memory_command.notice == "共享预算暂停，原话已保留。"
        complete(runtime, turn, answer=turn.memory_command.notice)
        assert not engine.calls
        assert runtime.source_status(turn.event.event_id)["state"] == "archived"
        result = backend.run("合成网页原话", (), session_id="web:synthetic")
        assert result["answer_source"] == "application_command"
        assert result["answer"] == "共享预算暂停，原话已保留。"
    finally: backend.close()
