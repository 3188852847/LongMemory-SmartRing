"""只用合成临时库和本地替身；不访问校园模型或个人数据库。"""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import threading

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.entrypoints.api.chat_backend import ChatBackend
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from datetime import UTC, datetime


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "synthetic.db"
    LongMemoryV1(path).close()
    return path


def test_web_and_other_method_share_memory_without_sharing_session_history(database):
    web = ChatBackend(database, FakeAnswerGenerator())
    first = web.run("我养了一只叫豆包的猫", ())
    assert first["status"] == "completed" and first["user_saved"] and first["assistant_saved"]
    assert first["writes"][0]["operation"] == "add"
    other = LongMemoryV1(database)
    assert "豆包" in other.recall("我的猫叫什么").context
    other.close()
    result = ChatBackend(database, FakeAnswerGenerator()).run("我的猫叫什么", ())
    assert result["writes"] == [] and result["history_messages"] == 0
    assert "豆包" in result["answer"]
    assert result["retrieved"][0]["source_event_ids"] == (first["event_id"],)
    assert result["memory_context"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 4


def test_model_failure_preserves_actual_write_trace_but_not_assistant_fact(database):
    class Broken:
        def generate(self, **kwargs):
            raise AnswerGenerationError("secret-should-not-leak")
    result = ChatBackend(database, Broken()).run("我养了一只叫豆包的猫", ())
    assert result["status"] == "failed" and result["user_saved"]
    assert result["writes"][0]["operation"] == "add"
    assert result["answer"] is None and not result["assistant_saved"]
    assert "secret-should-not-leak" not in json.dumps(result)


def test_missing_and_old_database_not_created_or_migrated(tmp_path):
    missing = tmp_path / "missing.db"
    result = ChatBackend(missing, FakeAnswerGenerator()).run("你好", ())
    assert result["status"] == "failed" and not missing.exists()
    old = tmp_path / "old.db"
    with sqlite3.connect(old) as connection:
        connection.execute("PRAGMA user_version = 1")
    before = old.read_bytes()
    result = ChatBackend(old, FakeAnswerGenerator()).run("你好", ())
    assert result["status"] == "failed" and old.read_bytes() == before


def test_atomic_observe_rolls_back_l0_when_extraction_fails(database):
    method = LongMemoryV1(database)
    def fail(message):
        raise RuntimeError("synthetic extraction failure")
    method.extractor.extract = fail
    with pytest.raises(RuntimeError):
        method.observe(MemoryEvent("synthetic-event", "user", "我喜欢猫", datetime.now(UTC)))
    assert method.connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
    method.close()


def test_two_connections_deduplicate_in_same_write_transaction(database):
    barrier = threading.Barrier(2)
    def write(index):
        method = LongMemoryV1(database, existing_only=True)
        try:
            barrier.wait(timeout=3)
            return method.observe(MemoryEvent(str(index), "user", "我养了一只叫豆包的猫", datetime.now(UTC)))
        finally:
            method.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sorted(item.writes[0].operation for item in results) == ["add", "noop"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0] == 2


def test_model_payload_preserves_roles_and_legacy_generate_protocol(database):
    payloads = []
    def transport(settings, body):
        payloads.append(json.loads(body))
        return 200, b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
    generator = OpenAICompatibleAnswerGenerator(
        ModelSettings(provider="openai_compatible", base_url="https://synthetic.invalid/v1", api_key="synthetic", model="test"),
        transport=transport, role_prompt="synthetic role",
    )
    history = ({"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上个回答"})
    result = ChatBackend(database, generator, provider="openai_compatible").run("继续", history)
    assert result["status"] == "completed"
    assert payloads[0]["messages"][-3:] == [*history, {"role": "user", "content": "继续"}]
    assert payloads[0]["messages"][1]["content"] == "synthetic role"
    generator.generate(query="独立问题", memory_context="")
    assert "上一句" not in json.dumps(payloads[1], ensure_ascii=False)
