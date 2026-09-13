"""P3.2 日常提取：验证 L0 优先、显式失败和现有库复用。"""

from datetime import UTC, datetime
import json
import sqlite3
import pytest

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


def audit_rows(path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT phase,outcome_code,candidate_count,added_count,provider,model "
            "FROM l1_extraction_events ORDER BY occurred_at,rowid"
        ).fetchall()


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
    assert audit_rows(path) == [
        ("started", None, None, None, "synthetic", "synthetic"),
        ("completed", "added", 1, 1, "synthetic", "synthetic"),
    ]


def test_deferred_phases_reuse_archived_l0_without_duplicate_source(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    source = event("source-deferred", "我叫小林")

    method.archive(source)
    extracted = method.extract_archived(source)
    result = method.persist_archived(source, extracted)

    assert result.writes[0].operation == "add"
    assert producer.calls == 1
    method.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM conversation_messages"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM memory_evidence"
        ).fetchone()[0] == 1


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
    assert [row[:4] for row in audit_rows(path)] == [
        ("started", None, None, None),
        ("failed", "extraction_failed", 0, 0),
    ]


def test_failed_source_can_be_recovered_once_without_copying_l0(tmp_path):
    path = existing_database(tmp_path)

    class RecoveringProducer:
        def __init__(self):
            self.calls = 0

        def propose(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise OSError("synthetic first failure")
            return proposal()

    method = DailyLLMMemory(path, producer=RecoveringProducer())
    assert method.observe(event("source-retry", "我叫小林")).processing_status == "source_only"
    with sqlite3.connect(path) as connection:
        failed_attempt = connection.execute(
            "SELECT attempt_id FROM l1_extraction_events WHERE phase='started'"
        ).fetchone()[0]

    recovered_event, recovery_attempt = method.prepare_failed_observation_recovery(
        "source-retry", expected_attempt_id=failed_attempt,
    )
    extracted = method.extract_archived(recovered_event, start_audit=False)
    result = method.persist_archived(recovered_event, extracted)

    assert recovery_attempt != failed_attempt
    assert result.writes[0].operation == "add"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
    with pytest.raises(ValueError, match="l1_retry_stale"):
        method.prepare_failed_observation_recovery(
            "source-retry", expected_attempt_id=failed_attempt,
        )
    method.close()


def test_completed_noop_cannot_be_reprocessed_as_failure(tmp_path):
    path = existing_database(tmp_path)
    method = DailyLLMMemory(path, producer=Stub(proposal()))
    method.observe(event("question-no-retry", "我叫什么？"))
    with sqlite3.connect(path) as connection:
        attempt_id = connection.execute(
            "SELECT attempt_id FROM l1_extraction_events WHERE phase='started'"
        ).fetchone()[0]
    with pytest.raises(ValueError, match="l1_retry_not_available"):
        method.prepare_failed_observation_recovery(
            "question-no-retry", expected_attempt_id=attempt_id,
        )
    method.close()


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
    assert [row[:4] for row in audit_rows(path)] == [
        ("started", None, None, None),
        ("failed", "persistence_failed", 1, 0),
    ]


def test_question_is_completed_noop_not_extraction_failure(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal())
    method = DailyLLMMemory(path, producer=producer)
    result = method.observe(event("question", "我叫什么？"))
    assert result.processing_status == "completed" and result.writes == ()
    assert producer.calls == 0
    method.close()
    assert [row[:4] for row in audit_rows(path)] == [
        ("started", None, None, None),
        ("completed", "noop", 0, 0),
    ]


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
    assert [row[:4] for row in audit_rows(path)] == [
        ("started", None, None, None),
        ("completed", "added", 1, 1),
        ("started", None, None, None),
        ("completed", "reused", 1, 0),
    ]


def test_daily_llm_scopes_explicit_today_state_and_allows_next_day_recurrence(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal("用户今天心情不好。", "我今天心情不好"))
    method = DailyLLMMemory(path, producer=producer)
    first = event("mood-day-1", "我今天心情不好")
    second = MemoryEvent(
        "mood-day-2", "user", "我今天心情不好",
        datetime(2026, 9, 7, tzinfo=UTC),
    )

    assert method.observe(first).writes[0].operation == "add"
    assert method.observe(second).writes[0].operation == "add"
    method.close()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT valid_from,valid_to FROM atomic_memories ORDER BY valid_from"
        ).fetchall()
    assert rows == [
        ("2026-09-06T00:00:00+08:00", "2026-09-07T00:00:00+08:00"),
        ("2026-09-07T00:00:00+08:00", "2026-09-08T00:00:00+08:00"),
    ]


def test_daily_llm_scopes_supported_temporary_interaction_wording(tmp_path):
    path = existing_database(tmp_path)
    producer = Stub(proposal(
        "用户希望助手今天只倾听，不主动给建议。",
        "我今天只想让你听我说",
    ))
    method = DailyLLMMemory(path, producer=producer)

    method.observe(event("listen-today", "我今天只想让你听我说"))
    method.close()

    with sqlite3.connect(path) as connection:
        valid_to = connection.execute(
            "SELECT valid_to FROM atomic_memories"
        ).fetchone()[0]
    assert valid_to == "2026-09-07T00:00:00+08:00"
