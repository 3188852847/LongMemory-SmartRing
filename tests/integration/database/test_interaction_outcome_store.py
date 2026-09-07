from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_conversation_store import (
    SQLiteConversationStore,
)
from longmemory.adapters.storage.sqlite_interaction_outcome_store import (
    RECORDER_VERSION,
    SQLiteInteractionOutcomeStore,
)
from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.application.proactive import ProactiveOutreachLedger
from longmemory.bootstrap import build_memory_runtime
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.core.proactive import OutreachEvidence, OutreachState, OutreachTrigger
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 5, 0, tzinfo=UTC)


def _create_outreach(
    connection,
    *,
    trigger=OutreachTrigger.EXPLICIT_SCHEDULE,
    reason="scheduled_daily_greeting",
    suffix="formal",
    queue=True,
):
    ids = iter((
        f"outreach-{suffix}", f"created-{suffix}", f"queued-{suffix}",
    ))
    ledger = ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection),
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    outreach = ledger.create_candidate(
        subject_id="user:self",
        trigger=trigger,
        trigger_reason_code=reason,
        content="下午好，今天过得怎么样？",
        scheduled_for=NOW,
        expires_at=NOW + timedelta(minutes=5),
        idempotency_key=f"schedule-{suffix}",
    )
    if queue:
        ledger.record_transition(
            outreach.id,
            expected_revision=1,
            new_state=OutreachState.QUEUED,
            reason_code="scheduled_delivery_started",
            evidence=OutreachEvidence.SERVER_QUEUE,
        )
    return outreach


def _save_user_and_observe(connection, message_id, created_at):
    message = ConversationMessage(
        id=MessageId(message_id),
        role=MessageRole.USER,
        content="这是私人原文，不应复制到互动结果事件。",
        created_at=created_at,
    )
    SQLiteConversationStore(connection).save(message)
    return SQLiteInteractionOutcomeStore(
        connection, id_factory=lambda: f"outcome-{message_id}",
    ).record_user_message(message)


def test_first_user_message_after_formal_outreach_records_temporal_evidence(tmp_path):
    connection = open_database(tmp_path / "outcome.db")
    initialize_schema(connection)
    outreach = _create_outreach(connection)

    event = _save_user_and_observe(connection, "message-1", NOW + timedelta(minutes=3))
    duplicate = _save_user_and_observe(connection, "message-2", NOW + timedelta(minutes=4))

    assert event is not None
    assert event.outreach_id == outreach.id
    assert event.source_message_id == "message-1"
    assert event.latency_seconds == 180
    assert event.evidence.value == "temporal_order"
    assert event.recorder_version == RECORDER_VERSION
    assert duplicate is None
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(companion_interaction_events)"
        )
    }
    assert "content" not in columns
    assert connection.execute(
        "SELECT count(*) FROM companion_interaction_events"
    ).fetchone()[0] == 1
    connection.close()


def test_manual_and_development_outreach_are_not_learning_evidence(tmp_path):
    connection = open_database(tmp_path / "excluded.db")
    initialize_schema(connection)
    _create_outreach(
        connection,
        trigger=OutreachTrigger.MANUAL_TEST,
        reason="manual_probe",
        suffix="manual",
    )
    _create_outreach(
        connection,
        reason="development_approved_memory_topic",
        suffix="development",
    )

    assert _save_user_and_observe(
        connection, "message-excluded", NOW + timedelta(minutes=2),
    ) is None
    assert connection.execute(
        "SELECT count(*) FROM companion_interaction_events"
    ).fetchone()[0] == 0
    connection.close()


def test_real_memory_runtime_records_outcome_without_copying_message_body(tmp_path):
    database = tmp_path / "runtime.db"
    connection = open_database(database)
    initialize_schema(connection)
    outreach = _create_outreach(connection, suffix="runtime")
    connection.close()

    runtime = build_memory_runtime(database)
    runtime.prepare_user("我今天有点累，这是不应复制的消息正文。")
    runtime.close()

    connection = open_database(database)
    row = connection.execute(
        "SELECT outreach_id,source_message_id,evidence_kind "
        "FROM companion_interaction_events"
    ).fetchone()
    assert tuple(row) == (outreach.id, row["source_message_id"], "temporal_order")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    connection.close()


def test_v19_upgrade_adds_an_empty_outcome_table(tmp_path):
    connection = open_database(tmp_path / "v19.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_interaction_source_message;
        DROP INDEX idx_companion_interaction_subject_recent;
        DROP TABLE companion_interaction_events;
        PRAGMA user_version=19;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_interaction_events"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_history_distinguishes_no_delivery_waiting_and_observed(tmp_path):
    database = tmp_path / "history.db"
    connection = open_database(database)
    initialize_schema(connection)
    not_delivered = _create_outreach(
        connection, suffix="not-delivered", queue=False,
    )
    waiting = _create_outreach(connection, suffix="waiting")
    observed = _create_outreach(connection, suffix="zz-observed")
    _save_user_and_observe(connection, "message-observed", NOW + timedelta(minutes=2))
    connection.close()

    items = {
        item["outreach_id"]: item
        for item in MemoryBackend(database).proactive_history(limit=10)["items"]
    }
    assert items[not_delivered.id]["outcome_observation_state"] == (
        "delivery_not_established"
    )
    assert items[not_delivered.id]["delivery_evidence_level"] is None
    assert items[waiting.id]["outcome_observation_state"] == (
        "awaiting_subsequent_user_message"
    )
    assert items[waiting.id]["delivery_evidence_level"] == "server_queued"
    assert items[observed.id]["outcome_observation_state"] == (
        "subsequent_user_message_observed"
    )
