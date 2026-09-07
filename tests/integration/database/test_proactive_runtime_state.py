from datetime import datetime, timedelta, timezone

from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.adapters.storage.sqlite_proactive_runtime_state import (
    SQLiteProactiveHistoryReader,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.core.proactive import OutreachEvidence, OutreachState, OutreachTrigger
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)


def make_ledger(connection, times):
    values = iter(times)
    ids = iter(f"runtime-{number}" for number in range(20))
    return ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection),
        clock=lambda: next(values), id_factory=lambda: next(ids),
    )


def create(ledger, key):
    return ledger.create_candidate(
        subject_id="user:self", trigger=OutreachTrigger.MANUAL_TEST,
        trigger_reason_code="synthetic", content="合成问候。",
        scheduled_for=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(minutes=5), idempotency_key=key,
    )


def test_attempts_and_real_user_message_determine_awaiting_state(tmp_path):
    connection = open_database(tmp_path / "runtime.db")
    initialize_schema(connection)
    queued_at = NOW - timedelta(hours=1)
    ledger = make_ledger(connection, [NOW - timedelta(hours=2), queued_at])
    outreach = create(ledger, "first")
    ledger.record_transition(
        outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="ready", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    reader = SQLiteProactiveHistoryReader(connection)
    before_reply = reader.read("user:self", now=NOW)
    assert before_reply.attempted_at == (queued_at,)
    assert before_reply.awaiting_user_response is True

    connection.execute(
        "INSERT INTO conversation_messages VALUES (?,?,?,?)",
        ("reply", "user", "合成回复。", (queued_at + timedelta(minutes=1)).isoformat()),
    )
    connection.commit()
    assert reader.read("user:self", now=NOW).awaiting_user_response is False
    connection.close()


def test_failed_attempt_counts_for_rate_limit_but_does_not_await_reply(tmp_path):
    connection = open_database(tmp_path / "failed.db")
    initialize_schema(connection)
    queued_at = NOW - timedelta(hours=1)
    ledger = make_ledger(
        connection, [NOW - timedelta(hours=2), queued_at, queued_at + timedelta(seconds=1)],
    )
    outreach = create(ledger, "failed")
    queued = ledger.record_transition(
        outreach.id, expected_revision=1, new_state=OutreachState.QUEUED,
        reason_code="ready", evidence=OutreachEvidence.SERVER_QUEUE,
    )
    ledger.record_transition(
        queued.id, expected_revision=2, new_state=OutreachState.FAILED,
        reason_code="device_offline", evidence=OutreachEvidence.SERVER_QUEUE,
        failure_reason="device_offline",
    )
    state = SQLiteProactiveHistoryReader(connection).read("user:self", now=NOW)
    assert state.attempted_at == (queued_at,)
    assert state.awaiting_user_response is False
    connection.close()
