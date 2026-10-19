from datetime import UTC, datetime
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from longmemory.methods.hy_memory.settings import Endpoint, HySettings, load_offline_settings
from longmemory.methods.hy_memory.process_client import HyProcessClient, clean_environment
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.worker import RequestBudget
from longmemory.methods.hy_memory.assembly import assemble_hy_backend


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/hy_memory_fake_worker.py"
spec = importlib.util.spec_from_file_location("hy_persistent_fake", FIXTURE)
fake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fake)
SETTINGS = HySettings(user_id="v-synthetic-only")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
EVENT = MemoryEvent("event-1", "user", "合成用户喜欢无糖茶", NOW, "session-1")


def open_runtime(root, *, create, settings=SETTINGS, factory=fake.PersistentFakeClient):
    return build_hy_memory_runtime(settings=settings, state_directory=root / "engine",
        source_path=root / "sources.db", create=create, client_factory=factory)


def test_u_runtime_archives_assistant_and_replays_completed_after_restart(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    observation = runtime._method.observe(EVENT)
    assert observation.writes is None
    runtime._method.observe(EVENT)
    assistant = replace(EVENT, event_id="assistant-1", role="assistant", content="你可以养兔子")
    runtime._method.observe(assistant)
    assert runtime.source_detail("assistant-1")["role"] == "assistant"
    support = runtime._method.recall("偏好是什么")
    assert support.retrieved[0].source_event_ids == ("event-1",)
    assert support.retrieved[0].dense_score is None
    assert support.warning_code == "hy_recall_may_mutate_state"
    assert not runtime.status()["method_capabilities"]["idempotent_observation"]
    runtime.close()
    reopened = open_runtime(tmp_path, create=False)
    try:
        assert reopened.source_detail("event-1")["session_id"] == "session-1"
        assert reopened._method.observe(EVENT) == observation
        assert reopened._method.recall("偏好").context == EVENT.content
        data = json.loads((tmp_path / "engine/sdk/fake.json").read_text(encoding="utf-8"))
        assert data["adds"] == 1
        with pytest.raises(ValueError, match="conflict"):
            reopened._method.observe(replace(EVENT, content="冲突载荷"))
    finally:
        reopened.close()


def test_partial_write_failure_is_audited_without_blind_retry(tmp_path):
    def failure(root, *, create):
        client = fake.PersistentFakeClient(root, create=create)
        client.fail_after = True
        return client
    runtime = open_runtime(tmp_path, create=True, factory=failure)
    result = runtime._method.observe(EVENT)
    assert result.processing_status == "source_only"
    assert runtime.source_status(EVENT.event_id)["state"] == "failed"
    runtime.close()
    reopened = open_runtime(tmp_path, create=False)
    try:
        assert reopened._method.observe(EVENT).warning_code == "engine_explicit_retry_required"
        status = reopened.source_status(EVENT.event_id)
        with pytest.raises(UnsupportedCapabilityError, match="idempotency"):
            reopened.retry_source(EVENT.event_id, expected_attempt_id=status["attempt_id"])
        assert reopened.source_detail(EVENT.event_id)["content"] == EVENT.content
        data = json.loads((tmp_path / "engine/sdk/fake.json").read_text(encoding="utf-8"))
        assert data["adds"] == 1
    finally:
        reopened.close()


def test_management_read_only_and_unknown_times(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    try:
        runtime._method.observe(EVENT)
        page = runtime.administer("listing", "list_items", state="active")
        assert page.total == 1
        item = runtime.administer("detail", "get_item", page.items[0].item_id)
        assert item.kind == "l2_fact" and item.valid_from is item.recorded_at is None
        assert item.source_event_ids == ("event-1",)
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer("correction", "correct_item", item.item_id, "修改", expected_revision=item.revision, source=EVENT)
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer("deletion", "delete_item", item.item_id, expected_revision=item.revision)
        with pytest.raises(UnsupportedCapabilityError, match="filter"):
            runtime.administer("listing", "list_items", query="茶")
        with pytest.raises(LookupError):
            runtime.administer("detail", "get_item", "missing")
        assert not runtime.legacy_sqlite
    finally:
        runtime.close()


def test_management_rejects_foreign_owner(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    try:
        runtime._method.observe(EVENT)
        raw_client = runtime._method.engine._client.client
        raw_client.data["rows"][0]["user_id"] = "other-user"
        with pytest.raises(UnsupportedCapabilityError, match="owner_scope"):
            runtime.administer("detail", "get_item", "item-event-1")
    finally:
        runtime.close()


def test_state_and_source_path_guards(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    with pytest.raises(FileExistsError):
        open_runtime(tmp_path, create=True)
    with pytest.raises((OSError, ValueError)):
        open_runtime(tmp_path, create=False)
    runtime.close()
    with pytest.raises(ValueError, match="identity"):
        open_runtime(tmp_path, create=False, settings=replace(SETTINGS, embedding_dimensions=16))
    with pytest.raises(ValueError, match="overlap"):
        build_hy_memory_runtime(settings=SETTINGS, state_directory=tmp_path / "wrong",
            source_path=tmp_path / "wrong/sources.db", create=True, client_factory=fake.PersistentFakeClient)
    assert not (tmp_path / "wrong").exists()


def test_missing_store_does_not_recreate(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    runtime.close()
    (tmp_path / "engine/sdk/fake.json").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        open_runtime(tmp_path, create=False)
    assert not (tmp_path / "engine/sdk/fake.json").exists()


def test_another_source_journal_cannot_bypass_active_engine_owner(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    try:
        with pytest.raises(OSError):
            assemble_hy_backend(settings=SETTINGS,state_directory=tmp_path / "engine",
                source_path=tmp_path / "another-sources.db",create=False,create_sources=True,
                client_factory=fake.PersistentFakeClient)
        assert runtime._method.observe(EVENT).processing_status == "completed"
    finally:
        runtime.close()


def test_process_roundtrip_and_reopen_fake_only(tmp_path):
    command = [sys.executable, "-I", "-X", "utf8", "-B", str(FIXTURE)]
    def factory(root, *, create):
        return HyProcessClient(python=Path(sys.executable), workspace=root, settings=SETTINGS, create=create, command=command)
    runtime = open_runtime(tmp_path, create=True, factory=factory)
    runtime._method.observe(EVENT)
    assert runtime._method.recall("查询").retrieved[0].content == EVENT.content
    assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    runtime.close()
    reopened = open_runtime(tmp_path, create=False, factory=factory)
    try:
        assert reopened._method.recall("查询").context == EVENT.content
    finally:
        reopened.close()


def test_environment_omits_ambient_keys_and_sdk_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unwanted")
    monkeypatch.setenv("MEMORY_PERSIST_DIR", "wrong-directory")
    env = clean_environment(tmp_path)
    assert "OPENAI_API_KEY" not in env and "MEMORY_PERSIST_DIR" not in env
    assert env["MEMORY_SEARCH_DEDUP_ENABLED"] == "false"
    assert env["USERPROFILE"] == str(tmp_path / "home")


def test_network_budget_default_denies_and_cap_is_shared():
    with pytest.raises(RuntimeError, match="denied"):
        RequestBudget(SETTINGS).claim("https://blocked.invalid/v1/embeddings")
    endpoint = Endpoint("https://synthetic.example/v1", "synthetic-model", "synthetic-key")
    budget = RequestBudget(replace(SETTINGS, network_authorized=True, max_external_requests=2, llm=endpoint, embedding=endpoint))
    with pytest.raises(RuntimeError, match="denied"):
        budget.claim("https://synthetic.example.evil/v1/embeddings")
    budget.claim("https://synthetic.example/v1/embeddings")
    budget.claim("https://synthetic.example/v1/chat/completions")
    with pytest.raises(RuntimeError, match="exhausted"):
        budget.claim("https://synthetic.example/v1/embeddings")
    assert budget.report()["cost"] is None


def test_offline_config_and_public_metadata_do_not_contain_keys(tmp_path):
    assert not load_offline_settings(ROOT / "config/examples/hy-memory/offline-settings.json").network_authorized
    endpoint = Endpoint(api_key="synthetic-secret")
    settings = replace(SETTINGS, llm=endpoint)
    assert "synthetic-secret" not in repr(settings)
    assert "synthetic-secret" not in json.dumps(settings.public())
    path = tmp_path / "bad.json"
    path.write_text('{"user_id":"synthetic","network_authorized":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown_field"):
        load_offline_settings(path)


def test_hy_same_u_http_boundary_and_unsupported_legacy_routes(tmp_path):
    import asyncio
    import socket
    from aiohttp import ClientSession, CookieJar, web
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.entrypoints.api.server import create_app
    class Bridge:
        async def close(self): pass
    async def run():
        runtime = open_runtime(tmp_path,create=True)
        chat = ChatBackend(tmp_path / "sources.db",FakeAnswerGenerator(),runtime=runtime)
        sock = socket.socket()
        sock.bind(("127.0.0.1",0))
        port = sock.getsockname()[1]
        assert port not in {8767,8000,8003}
        base = f"http://127.0.0.1:{port}"
        app = create_app(port=port,bridge=Bridge(),chat_backend=chat,memory_runtime=runtime,
            database=tmp_path / "sources.db",allow_memory_delete=True,allow_memory_correction=True,
            observability_root=tmp_path)
        runner = web.AppRunner(app,access_log=None)
        try:
            await runner.setup()
            await web.SockSite(runner,sock).start()
            async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
                assert (await client.get(base + "/api/memory-engine")).status == 401
                csrf = await (await client.get(base + "/api/session",headers={"X-Console-Bootstrap":"1"})).json()
                headers = {"Origin":base,"X-Console-CSRF":csrf["csrf"]}
                result = await asyncio.to_thread(chat.run,"合成用户喜欢无糖茶",())
                assert result["status"] == "completed" and result["assistant_saved"]
                info = await (await client.get(base + "/api/memory-engine")).json()
                assert info["method"] == "hy_memory_pro_chat" and not info["allow_correction"] and not info["allow_delete"]
                page = await (await client.get(base + "/api/memory-engine/items")).json()
                item = page["items"][0]
                detail = await (await client.get(base + "/api/memory-engine/items/" + item["item_id"])).json()
                assert detail["kind"] == "l2_fact"
                source = await (await client.get(base + "/api/memory-engine/sources/" + item["source_event_ids"][0])).json()
                assert source["role"] == "user"
                for path in ("/api/memories","/api/personas","/api/scenarios","/api/proactive-policy"):
                    assert (await client.get(base + path)).status == 501
                url = base + "/api/memory-engine/items/" + item["item_id"]
                assert (await client.post(url + "/corrections",headers=headers,json={"content":"修改","revision":item["revision"]})).status == 501
                assert (await client.delete(url,headers=headers,json={"revision":item["revision"]})).status == 501
        finally:
            await runner.cleanup()
            chat.close()
            sock.close()
    asyncio.run(run())
