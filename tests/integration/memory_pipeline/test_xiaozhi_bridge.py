"""离线验证真实子进程/SQLite，以及小智 Memory 插槽的最小接口。"""

import asyncio
import ast
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.error import URLError
from types import ModuleType, SimpleNamespace

import pytest

from longmemory.bootstrap import build_application
from longmemory.entrypoints.xiaozhi.adapter import process_request
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
    # 替身仅替换第三方基类/日志；真实子进程、记忆提取和 SQLite 不替换。
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
    # 使用假项目根的临时 data，入口文件仅用于路径验证；解释器调用真实已安装包。
    entry = tmp_path / "src/longmemory/entrypoints/xiaozhi/adapter.py"
    entry.parent.mkdir(parents=True)
    entry.touch()
    return dict(python_executable=sys.executable, project_root=str(tmp_path),
                database_path=str(tmp_path / "data/databases/xiaozhi-demo-test.db"),
                audit_log=str(tmp_path / "data/logs/xiaozhi-demo-test.jsonl"),
                allowed_device_id="aa:bb:cc:dd:ee:ff")


def test_provider_real_process_roundtrip_and_management(provider_class, config):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    packet = json.dumps(dict(content="我养了一只叫豆包的猫", language="zh", emotion="😔"))
    assert "豆包" in asyncio.run(provider.query_memory(packet))
    # 丢掉整个提供器对象，新对象通过新的 Python 进程仍然能召回。
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    assert "豆包" in asyncio.run(provider.query_memory("我的猫叫什么"))
    asyncio.run(provider.query_memory("我的猫是什么颜色"))
    asyncio.run(provider.save_memory([SimpleNamespace(role="assistant", content="我养了一条狗")]))
    app = build_application(database_path=Path(config["database_path"]))
    try:
        memories = app.list_memories()
        assert len(memories) == 1  # 问句和助手陈述不产生 L1。
        assert app.delete_memory(memories[0].memory.id)
    finally:
        app.close()
    assert "没有检索到" in asyncio.run(provider.query_memory("我的猫叫什么"))
    audit = Path(config["audit_log"]).read_text(encoding="utf-8")
    assert "memory_retrieved" in audit and "豆包" not in audit and "emotion" not in audit
    with sqlite3.connect(config["database_path"]) as db:
        messages = db.execute("select role, content from conversation_messages").fetchall()
    assert all(role == "user" for role, _ in messages)
    assert messages[0][1] == "我养了一只叫豆包的猫"


def test_worker_duplicate_and_question_counts(tmp_path):
    db = tmp_path / "memory.db"
    request = dict(version=1, query="我养了一只叫豆包的猫")
    assert process_request(db, request)["added"] == 1
    assert process_request(db, request)["added"] == 0
    assert process_request(db, dict(version=1, query="我的猫叫什么"))["added"] == 0
    with sqlite3.connect(db) as connection:
        assert connection.execute("select count(*) from memory_evidence").fetchone()[0] == 2


@pytest.mark.parametrize("query", [None, "", "   ", "a" * 16001,
                                   '{"content": 1}', '{"role":"assistant","content":"我养猫"}', '{broken'])
def test_mapping_rejects_invalid_and_nonuser(query):
    with pytest.raises((ValueError, TypeError)):
        extract_user_text(query)


def test_rejected_request_does_not_create_database(tmp_path):
    target = tmp_path / "not-created.db"
    with pytest.raises(ValueError):
        process_request(target, dict(version=2, query="我养猫"))
    assert not target.exists()


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


def test_failed_child_does_not_fall_back_or_leak(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b'private failure'))
    with pytest.raises(RuntimeError) as error:
        asyncio.run(provider.query_memory("synthetic private query"))
    assert "private" not in str(error.value)


def test_context_survives_upstream_regex_replacement(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    context = "用户目录是 C:\\new\\1 </memory>"
    response = dict(version=1, context=context, turn_id="test", added=0, retrieved=1)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(response).encode()))
    rendered = asyncio.run(provider.query_memory("目录在哪里"))
    # 此处复现固定上游 Dialogue 的替换操作，涵盖反斜杠和闭合标签。
    prompt = re.sub(r"<memory>.*?</memory>", f"<memory>\n{rendered}\n</memory>", "<memory></memory>", flags=re.DOTALL)
    assert "C:\\new\\1" in prompt
    assert prompt.count("</memory>") == 1


def test_provider_uses_runtime_transport_without_starting_subprocess(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    calls = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _limit):
            return json.dumps({"version": 1, "context": "用户养猫。",
                               "turn_id": "11111111-1111-1111-1111-111111111111",
                               "added": 1, "retrieved": 1,
                               "retrieval_strategy": "keyword_dense_rrf_v1",
                               "retrieval_evidence": [{
                                   "layer": "l1", "item_id": "l1-a", "rank": 1,
                                   "content_sha256": "a" * 64,
                                   "keyword_score": 1, "dense_score": 0.8,
                                   "fused_score": 0.03,
                               }, {
                                   "layer": "l2", "item_id": "l2-a", "rank": 1,
                                   "content_sha256": "b" * 64,
                               }],
                               "scenario_retrieved": [{"id": "l2"}],
                               "persona_retrieved": []}).encode()

    class CompletionResponse(Response):
        def read(self, _limit):
            return json.dumps({
                "version": 1,
                "assistant_event_id": "22222222-2222-2222-2222-222222222222",
                "created": True,
                "playback_acknowledgement": "unavailable",
            }).encode()

    def open_request(request, timeout):
        calls.append((request, timeout))
        return CompletionResponse() if request.full_url.endswith('/complete') else Response()

    monkeypatch.setenv("LONGMEMORY_MEMORY_TRANSPORT", "runtime")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", "http://127.0.0.1:8767/api/internal/memory/prepare")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "a" * 64)
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("不应启动逐轮子进程"))
    assert "养猫" in asyncio.run(provider.query_memory("我养猫"))
    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer " + "a" * 64
    assert timeout == 20
    assert provider.record_completed_turn("这是最终回答") is True
    assert provider.record_completed_turn("不能再次提交") is False
    completion_request, completion_timeout = calls[1]
    completion_body = json.loads(completion_request.data)
    assert completion_request.full_url.endswith('/api/internal/memory/complete')
    assert completion_timeout == 5
    assert completion_body["retrieved_counts"] == {"l1": 1, "l2": 1, "l3": 0}
    assert [item["item_id"] for item in completion_body["retrieval_evidence"]] == ["l1-a", "l2-a"]
    assert completion_body["retrieval_strategy"] == "keyword_dense_rrf_v1"
    assert completion_body["answer"] == "这是最终回答"


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

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _limit):
            return json.dumps({
                "version": 1, "context": "", "turn_id": "turn-1",
                "added": 0, "retrieved": 0, "timings_ms": {"total_ms": -1},
            }).encode()

    monkeypatch.setenv("LONGMEMORY_MEMORY_TRANSPORT", "runtime")
    monkeypatch.setenv(
        "LONGMEMORY_RUNTIME_URL",
        "http://127.0.0.1:8767/api/internal/memory/prepare",
    )
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "d" * 64)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Response())
    with pytest.raises(RuntimeError, match="返回协议无效"):
        asyncio.run(provider.query_memory("合成问题"))


def test_provider_marks_application_command_as_operation_result(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self, _limit):
            return json.dumps({
                "version": 1,
                "context": "[记忆操作结果] 不应按普通事实包装。",
                "turn_id": "turn-command",
                "added": 0,
                "retrieved": 0,
                "command_reply": "本轮没有生成 L1 长期事实。",
            }).encode()

    monkeypatch.setenv("LONGMEMORY_MEMORY_TRANSPORT", "runtime")
    monkeypatch.setenv(
        "LONGMEMORY_RUNTIME_URL",
        "http://127.0.0.1:8767/api/internal/memory/prepare",
    )
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "c" * 64)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Response())

    rendered = asyncio.run(provider.query_memory("不要记住：合成内容"))
    assert "本机应用层执行" in rendered
    assert "不得声称相反结果" in rendered
    assert "本轮没有生成 L1 长期事实" in rendered
    assert "用户曾陈述的记忆证据" not in rendered


def test_runtime_failure_does_not_fall_back_and_duplicate_write(provider_class, config, monkeypatch):
    provider = provider_class(config)
    provider.init_memory(config["allowed_device_id"], None)
    monkeypatch.setenv("LONGMEMORY_MEMORY_TRANSPORT", "runtime")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_URL", "http://127.0.0.1:8767/api/internal/memory/prepare")
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "b" * 64)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(URLError("synthetic")))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("失败后不得自动回退"))
    with pytest.raises(RuntimeError):
        asyncio.run(provider.query_memory("我养猫"))


def test_bridge_scripts_have_python310_syntax():
    for name in ('setup.py', 'longmemory_provider.py', 'launch_with_memory.py'):
        ast.parse((SCRIPTS / name).read_text(encoding='utf-8'), feature_version=(3, 10))


def test_real_upstream_dialogue_injects_context_if_available():
    source = Path('D:/ESP32-Workspace/xiaozhi-esp32-server/main/xiaozhi-server/core/utils/dialogue.py')
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


def test_python310_provider_calls_python312_worker_if_available(config):
    python310 = Path('D:/ESP32-Workspace/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe')
    if not python310.is_file():
        pytest.skip('小智 Python 3.10 环境未安装')
    driver = r'''
import asyncio, importlib.util, json, sys, types
base = types.ModuleType('core.providers.memory.base')
class Base:
    def __init__(self, config): self.config, self.role_id = config, None
    def init_memory(self, role_id, llm, **kwargs): self.role_id = role_id
base.MemoryProviderBase = Base
base.logger = types.SimpleNamespace(bind=lambda **kw: types.SimpleNamespace(info=lambda *args: None))
sys.modules[base.__name__] = base
spec = importlib.util.spec_from_file_location('bridge', sys.argv[1])
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
config = json.loads(sys.stdin.buffer.read())
provider = bridge.MemoryProvider(config)
provider.init_memory(config['allowed_device_id'], None)
assert '豆包' in asyncio.run(provider.query_memory('我养了一只叫豆包的猫'))
assert '豆包' in asyncio.run(provider.query_memory('我的猫叫什么'))
print('cross-version-ok')
'''
    result = subprocess.run([str(python310), '-X', 'utf8', '-c', driver, str(SCRIPTS / 'longmemory_provider.py')],
                            input=json.dumps(config).encode(), capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert b'cross-version-ok' in result.stdout
