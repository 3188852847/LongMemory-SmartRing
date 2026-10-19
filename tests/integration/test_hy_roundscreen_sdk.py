"""真实 Hy SDK/存储与 Python 3.10 薄桥；模型为禁网 MockTransport。

仅从显式测试环境变量借用所有者已安装的解释器，不安装或复制环境。
"""

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest
from aiohttp import web

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.entrypoints.api.server import create_app
from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.round_screen_turns import memory_receipt


ROOT = Path(__file__).resolve().parents[2]
SDK_PYTHON = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-hy-interpreter"))
VOICE_PYTHON = Path(os.environ.get("LONGMEMORY_TEST_XIAOZHI_PYTHON", "missing-voice-interpreter"))


def open_runtime(directory, *, create):
    return build_hy_memory_runtime(settings=HySettings(user_id="synthetic-x-roundscreen", model_mode="synthetic_transport"),
        state_directory=directory / "Hy中文状态", source_path=directory / "平台来源.db",
        create=create, python=SDK_PYTHON, expected_python_version="3.12.13")


@pytest.mark.skipif(not SDK_PYTHON.is_file(), reason="explicit owner-installed Hy interpreter required")
def test_real_sdk_deferred_round_completion_recall_and_restart(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    try:
        turn, _ = runtime.prepare_round_screen("合成用户喜欢无糖乌龙茶", client_round_id="a" * 32, session_id="b" * 32)
        assert turn.support.retrieved == ()
        assert runtime.source_status(turn.event.event_id)["state"] == "pending"
        completion = runtime.complete_round_screen(turn_id=turn.event.event_id, answer="助手建议喝红茶",
            receipt=memory_receipt(turn), client_round_id="a" * 32)
        runtime.wait_for_deferred_observations()
        assert runtime.source_status(turn.event.event_id)["state"] == "completed"
        assert runtime.source_detail(completion.assistant_message_id)["role"] == "assistant"
        assert runtime.status()["state_identity"] == HySettings(user_id="synthetic-x-roundscreen", model_mode="synthetic_transport").identity()
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path, create=False)
    try:
        turn2, _ = runtime.prepare_round_screen("合成用户喜欢什么茶", client_round_id="c" * 32, session_id="d" * 32)
        assert "乌龙茶" in turn2.support.context
        assert all("红茶" not in item.content for item in turn2.support.retrieved)
        assert runtime.source_detail(turn.event.event_id)["session_id"] == "b" * 32
    finally:
        runtime.close()


@pytest.mark.skipif(not SDK_PYTHON.is_file(), reason="explicit owner-installed Hy interpreter required")
def test_actual_runtime_version_mismatch_rejects_and_releases_both_owners(tmp_path):
    with pytest.raises(ValueError, match="runtime_version_identity_mismatch"):
        build_hy_memory_runtime(settings=HySettings(user_id="synthetic-x-roundscreen", model_mode="synthetic_transport"),
            state_directory=tmp_path / "Hy中文状态", source_path=tmp_path / "平台来源.db",
            create=True, python=SDK_PYTHON, expected_python_version="9.9.9")
    runtime = open_runtime(tmp_path, create=False)
    try:
        assert runtime.status()["ready"]
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    finally:
        runtime.close()


@pytest.mark.skipif(not SDK_PYTHON.is_file() or not VOICE_PYTHON.is_file(), reason="explicit existing Hy and voice interpreters required")
def test_python310_real_provider_to_http312_and_real_hy_sdk(tmp_path):
    driver = r'''
import asyncio, importlib.util, json, sys, types
from pathlib import Path
assert sys.version_info[:2] == (3, 10)
source, config = sys.argv[1], json.loads(sys.stdin.buffer.read())
sys.path.insert(0, source)
base = types.ModuleType('core.providers.memory.base')
class Base:
    def __init__(self, config): self.config, self.role_id = config, None
    def init_memory(self, role_id, llm, **kwargs): self.role_id = role_id
base.MemoryProviderBase = Base
base.logger = types.SimpleNamespace(bind=lambda **kwargs: types.SimpleNamespace(info=lambda *args: None))
sys.modules[base.__name__] = base
import longmemory_provider, launch_with_memory
provider = longmemory_provider.MemoryProvider(config)
provider.init_memory(config['allowed_device_id'], None)
class Dialogue:
    def __init__(self): self.dialogue = []
    def put(self, message): self.dialogue.append(message)
class Connection:
    def __init__(self):
        self.memory, self.dialogue = provider, Dialogue()
        self.client_abort = False
        self.logger = types.SimpleNamespace(bind=lambda **kw: types.SimpleNamespace(error=lambda *args: (_ for _ in ()).throw(AssertionError('receipt failed'))))
    def chat(self, query, depth=0):
        asyncio.run(self.memory.query_memory(query))
        self.dialogue.put(types.SimpleNamespace(role='assistant', content='合成助手建议喝红茶'))
launch_with_memory.install_answer_completion(Connection)
connection = Connection()
connection.chat(json.dumps({'content':'合成用户喜欢无糖乌龙茶','emotion':'synthetic'}))
assert not provider._pending_completions
print('python310-neutral-completion-ok')
'''

    class Bridge:
        async def close(self): pass

    async def run():
        runtime = open_runtime(tmp_path, create=True)
        backend = ChatBackend(runtime.database, FakeAnswerGenerator(), runtime=runtime)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert port not in {8767, 8000, 8003, 8766, 8768, 18770}
        token = "e" * 64
        app = create_app(port=port, database=runtime.database, memory_runtime=runtime,
            chat_backend=backend, memory_runtime_token=token, bridge=Bridge(), observability_root=tmp_path)
        runner = web.AppRunner(app, access_log=None)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            fake_project = tmp_path / "fake-voice-project"
            entry = fake_project / "src/longmemory/entrypoints/xiaozhi/adapter.py"
            entry.parent.mkdir(parents=True)
            entry.touch()
            config = {"allowed_device_id": "synthetic-device", "python_executable": str(VOICE_PYTHON),
                "project_root": str(fake_project), "database_path": str(fake_project / "data/databases/xiaozhi-demo-synthetic.db"),
                "audit_log": str(fake_project / "data/logs/xiaozhi-demo-synthetic.jsonl")}
            env = os.environ.copy()
            env.update(LONGMEMORY_MEMORY_TRANSPORT="runtime", LONGMEMORY_RUNTIME_TOKEN=token,
                LONGMEMORY_RUNTIME_URL=f"http://127.0.0.1:{port}/api/internal/memory/prepare")
            result = await asyncio.to_thread(subprocess.run,
                [str(VOICE_PYTHON), "-I", "-X", "utf8", "-B", "-c", driver, str(ROOT / "scripts/development/xiaozhi")],
                input=json.dumps(config).encode(), capture_output=True, cwd=ROOT, env=env, timeout=45,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-2000:]
            assert b"python310-neutral-completion-ok" in result.stdout
            await asyncio.to_thread(runtime.wait_for_deferred_observations)
            events = runtime._method.journal.events()
            assert [event.role for event in events] == ["user", "assistant"]
            assert events[0].content == "合成用户喜欢无糖乌龙茶"
            assert events[0].session_id == events[1].session_id
            assert runtime.source_status(events[0].event_id)["state"] == "completed"
            page = runtime.administer("listing", "list_items", state="active")
            assert page.total == 1 and "乌龙茶" in page.items[0].content
            assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
        finally:
            await runner.cleanup()
            backend.close()
            sock.close()
    asyncio.run(run())
