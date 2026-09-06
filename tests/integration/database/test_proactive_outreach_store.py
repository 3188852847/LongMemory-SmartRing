from datetime import UTC, datetime, timedelta

import pytest

from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.core.proactive import (
    OutreachEvidence,
    OutreachState,
    OutreachTrigger,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class IDs:
    def __init__(self, prefix="id"):
        self.prefix = prefix
        self.value = 0

    def __call__(self):
        self.value += 1
        return f"{self.prefix}-{self.value}"


def ledger(connection, *, times=None, id_prefix="id"):
    values = iter(times or [NOW] * 20)
    return ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection),
        clock=lambda: next(values),
        id_factory=IDs(id_prefix),
    )


def create(item):
    return item.create_candidate(
        subject_id="user:self",
        trigger=OutreachTrigger.MANUAL_TEST,
        trigger_reason_code="manual_probe",
        content="这是一条合成主动播报。",
        scheduled_for=NOW,
        expires_at=NOW + timedelta(minutes=5),
        idempotency_key="probe-1",
    )


def test_projection_and_append_only_events_survive_reopen(tmp_path):
    path = tmp_path / "proactive.db"
    connection = open_database(path)
    initialize_schema(connection)
    item = ledger(connection, times=[NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)])
    outreach = create(item)
    queued = item.record_transition(
        outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="tts_queue_accepted", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    sent = item.record_transition(
        outreach.id, expected_revision=2, new_state=OutreachState.TRANSPORT_SENT,
        reason_code="websocket_write_completed", evidence=OutreachEvidence.TRANSPORT_WRITE,
    )
    connection.close()

    connection = open_database(path)
    store = SQLiteProactiveOutreachStore(connection)
    restored = store.get(outreach.id)
    assert restored == sent and restored.revision == 3
    events = store.list_events(outreach.id)
    assert [event.new_state for event in events] == [
        OutreachState.CANDIDATE, OutreachState.QUEUED, OutreachState.TRANSPORT_SENT,
    ]
    assert [event.sequence for event in events] == [1, 2, 3]
    connection.close()


def test_evidence_cannot_overclaim_delivery(tmp_path):
    connection = open_database(tmp_path / "evidence.db")
    initialize_schema(connection)
    item = ledger(connection)
    outreach = create(item)
    with pytest.raises(ValueError, match="outreach_evidence_does_not_support_state"):
        item.record_transition(
            outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
            reason_code="wrong_evidence", evidence=OutreachEvidence.TRANSPORT_WRITE,
        )
    assert SQLiteProactiveOutreachStore(connection).get(outreach.id).revision == 1
    connection.close()


def test_revision_conflict_and_idempotency_are_atomic(tmp_path):
    connection = open_database(tmp_path / "conflicts.db")
    initialize_schema(connection)
    item = ledger(connection, times=[NOW, NOW + timedelta(seconds=1)])
    outreach = create(item)
    queued = item.record_transition(
        outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="tts_queue_accepted", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    with pytest.raises(ValueError, match="outreach_transition_conflict"):
        item.record_transition(
            outreach.id, expected_revision=1, new_state=OutreachState.EXPIRED,
            reason_code="stale_page", evidence=OutreachEvidence.POLICY_DECISION,
        )
    # 第二次创建使用不同实体 ID，只让 (subject_id, idempotency_key) 重复，
    # 这样验证的是调度幂等边界，而不是碰巧撞上主键。
    other = ledger(connection, id_prefix="other")
    with pytest.raises(ValueError, match="outreach_idempotency_conflict"):
        create(other)
    store = SQLiteProactiveOutreachStore(connection)
    assert store.get(outreach.id) == queued
    assert len(store.list_events(outreach.id)) == 2
    connection.close()


def test_v13_upgrade_adds_empty_ledger_without_touching_memory(tmp_path):
    connection = open_database(tmp_path / "v13.db")
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
        "VALUES ('l1-existing','user:self','用户喜欢乌龙茶。',?)",
        (NOW.isoformat(),),
    )
    connection.executescript("""
        DROP INDEX idx_proactive_events_outreach;
        DROP TABLE proactive_outreach_events;
        DROP INDEX idx_proactive_outreach_due;
        DROP INDEX idx_proactive_outreach_recent;
        DROP TABLE proactive_outreach;
        PRAGMA user_version=13;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT content FROM atomic_memories WHERE id='l1-existing'"
    ).fetchone()[0] == "用户喜欢乌龙茶。"
    assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM proactive_outreach_events").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
