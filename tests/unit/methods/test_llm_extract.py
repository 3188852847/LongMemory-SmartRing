"""D1 装配验证：网络在事务外，写入原子化，冻结后绝不再提取。"""

from dataclasses import replace
from datetime import UTC, datetime
import json
import sqlite3

import pytest

from longmemory.core.memory.extraction.candidates import CandidateExtractionError
from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from longmemory.methods.llm_extract.method import LongMemoryLLMExtract
from longmemory.methods.longmemory_v1.method import LongMemoryV1
from longmemory.evaluation.comparison.methods import state_digest


def event(event_id="s1", content="职业：园艺师。爱好：徒步。", role="user"):
    return MemoryEvent(event_id, role, content, datetime(2026, 2, 1, tzinfo=UTC))


def proposal(facts=None):
    if facts is None:
        facts = [{"content": "用户是园艺师。", "quote": "职业：园艺师。"},
                 {"content": "用户喜欢徒步。", "quote": "爱好：徒步。"}]
    return json.dumps({"schema_version": 1, "operation": "ADD" if facts else "NOOP", "facts": facts}, ensure_ascii=False)


class Stub:
    def __init__(self, raw=None):
        self.raw, self.calls = raw if raw is not None else proposal(), 0
    def propose(self, *, source_text):
        self.calls += 1
        return self.raw


def test_network_before_transaction_and_atomic_restart_trace(tmp_path):
    path = tmp_path / "memory.db"
    class LockProbe(Stub):
        def propose(self, **kwargs):
            # 如果主连接已占写锁，第二个独立连接在这里会失败。
            with sqlite3.connect(path, timeout=0) as other:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            return super().propose(**kwargs)
    producer = LockProbe()
    method = LongMemoryLLMExtract(path, producer=producer)
    observation = method.observe(event())
    assert len(observation.writes) == 2 and all(op.operation == "add" for op in observation.writes)
    method.observe(event("assistant", "我猜你的职业是飞行员。", "assistant"))
    method.observe(event("question", "我的职业是什么"))
    assert producer.calls == 1
    method.close()
    before = state_digest(tmp_path)
    reopened = LongMemoryLLMExtract(path, read_only=True)
    assert "园艺师" in reopened.recall("职业园艺师").context
    assert reopened.recall("我是谁").retrieved == ()  # 没有趁提取升级修补关键词检索。
    with pytest.raises(RuntimeError):
        reopened.observe(event("forbidden"))
    reopened.close()
    reopened.close()
    assert state_digest(tmp_path) == before
    with sqlite3.connect(path) as conn:
        batch = json.loads(conn.execute("SELECT proposal_json FROM extraction_batches WHERE source_message_id='s1'").fetchone()[0])
        assert len(batch["candidates"]) == 2
        assert batch["candidates"][0]["source_quote"] == "职业：园艺师。"
        assert conn.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM memory_evidence").fetchone()[0] == 2


def test_exact_duplicate_keeps_multiple_sources_without_repeating_id_call(tmp_path):
    producer = Stub()
    method = LongMemoryLLMExtract(tmp_path / "memory.db", producer=producer)
    method.observe(event())
    second = method.observe(event("s2"))
    assert all(op.operation == "noop" for op in second.writes)
    assert set(method.recall("园艺师").retrieved[0].source_event_ids) == {"s1", "s2"}
    with pytest.raises(ValueError):
        method.observe(event("s2"))
    assert producer.calls == 2
    method.close()


def test_invalid_second_candidate_leaves_no_l0_l1_or_batch(tmp_path):
    invalid = proposal([{"content": "用户是园艺师。", "quote": "职业：园艺师。"},
                        {"content": "虚构", "quote": "不存在"}])
    path = tmp_path / "memory.db"
    method = LongMemoryLLMExtract(path, producer=Stub(invalid))
    with pytest.raises(CandidateExtractionError):
        method.observe(event())
    diagnostic = method.build_diagnostics()
    assert diagnostic["request_attempts"] == 1
    assert diagnostic["events"][0]["error"] == "extraction_failed"
    assert "proposal" not in diagnostic["events"][0]
    method.close()
    with sqlite3.connect(path) as conn:
        for table in ("conversation_messages", "atomic_memories", "memory_evidence", "extraction_batches"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_batch_audit_failure_rolls_back_all_prior_writes(tmp_path):
    path = tmp_path / "memory.db"
    method = LongMemoryLLMExtract(path, producer=Stub())
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON extraction_batches BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError):
        method.observe(event())
    assert method.build_diagnostics()["events"][0]["error"] == "persistence_failed"
    method.close()
    with sqlite3.connect(path) as conn:
        for table in ("conversation_messages", "atomic_memories", "memory_evidence", "extraction_batches"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_reject_existing_or_wrong_frozen_state_and_unsupported_session(tmp_path):
    path = tmp_path / "v1.db"
    LongMemoryV1(path).close()
    before = path.read_bytes()
    with pytest.raises(ValueError):
        LongMemoryLLMExtract(path, producer=Stub())
    with pytest.raises(sqlite3.OperationalError):
        LongMemoryLLMExtract(path, read_only=True)
    assert path.read_bytes() == before
    new_path = tmp_path / "new.db"
    with pytest.raises(ValueError):
        LongMemoryLLMExtract(new_path)
    assert not new_path.exists()
    producer = Stub()
    method = LongMemoryLLMExtract(new_path, producer=producer)
    with pytest.raises(UnsupportedCapabilityError):
        method.observe(replace(event(), session_id="not-supported"))
    assert producer.calls == 0
    method.close()


def test_interrupted_extraction_records_attempt_without_writes(tmp_path):
    class Stop:
        def propose(self, **kwargs):
            raise KeyboardInterrupt
    method = LongMemoryLLMExtract(tmp_path / "memory.db", producer=Stop())
    with pytest.raises(KeyboardInterrupt):
        method.observe(event())
    diagnostic = method.build_diagnostics()
    assert diagnostic["events"][0]["status"] == "interrupted"
    assert diagnostic["request_attempts"] == 1
    method.close()
