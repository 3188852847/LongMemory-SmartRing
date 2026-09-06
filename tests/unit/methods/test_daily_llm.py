"""P3.2 日常提取：验证 L0 优先、显式失败和现有库复用。"""

from datetime import UTC, datetime
import json
import sqlite3

from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.daily_llm.method import DailyLLMMemory
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def event(event_id: str, content: str, role: str = "user") -> MemoryEvent:
    return MemoryEvent(event_id, role, content, datetime(2026, 9, 6, tzinfo=UTC))


class Stub:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0

    def propose(self, *, source_text: str) -> str:
        self.calls += 1
        return self.raw


def proposal(content="用户叫小林。", quote="我叫小林"):
    return json.dumps({
        "schema_version": 1,
        "operation": "ADD",
        "facts": [{"content": content, "quote": quote}],
    }, ensure_ascii=False)


def existing_database(tmp_path):
    path = tmp_path / "daily.db"
    LongMemoryV1(path).close()
    return path


def test_daily_llm_reuses_existing_database_and_persists_valid_candidate(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    result = method.observe(event("source-1", "我叫小林"))
    assert result.processing_status == "completed"
    assert result.warning_code is None
    assert result.writes[0].operation == "add"
    # 本切片不伪装成语义召回升级；按候选中的字面实体检查即可。
    assert "小林" in method.recall("小林").context
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1


def test_extraction_failure_keeps_l0_and_reports_source_only(tmp_path):
    path = existing_database(tmp_path)

    class Broken:
        def propose(self, **_kwargs):
            raise OSError("synthetic network failure")

    method = DailyLLMMemory(path, producer=Broken())
    result = method.observe(event("source-1", "我叫小林"))
    assert result.writes == ()
    assert result.processing_status == "source_only"
    assert result.warning_code == "l1_extraction_failed"
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT content FROM conversation_messages").fetchone()[0] == "我叫小林"
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0


def test_l1_persistence_failure_keeps_l0_and_has_distinct_warning(tmp_path):
    path = existing_database(tmp_path)
    method = DailyLLMMemory(path, producer=Stub(proposal()))
    method._base.connection.execute("""
        CREATE TRIGGER synthetic_l1_failure BEFORE INSERT ON atomic_memories
        BEGIN SELECT RAISE(ABORT, 'synthetic'); END
    """)
    method._base.connection.commit()
    result = method.observe(event("source-1", "我叫小林"))
    assert result.processing_status == "source_only"
    assert result.warning_code == "l1_persistence_failed"
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0


def test_question_is_completed_noop_not_extraction_failure(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    result = method.observe(event("question", "我叫什么？"))
    assert result.processing_status == "completed" and result.writes == ()
    assert producer.calls == 0
    method.close()


def test_assistant_is_archived_without_becoming_user_fact(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    result = method.observe(event("assistant", "我猜你叫小林。", "assistant"))
    assert result.processing_status == "completed" and result.writes == ()
    assert producer.calls == 0
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT role FROM conversation_messages").fetchone()[0] == "assistant"
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0


def test_duplicate_fact_keeps_two_sources(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    assert method.observe(event("source-1", "我叫小林")).writes[0].operation == "add"
    assert method.observe(event("source-2", "我叫小林")).writes[0].operation == "noop"
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0] == 2
