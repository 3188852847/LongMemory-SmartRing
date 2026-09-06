import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from longmemory.adapters.storage.sqlite_proactive_outreach_store import (
    SQLiteProactiveOutreachStore,
)
from longmemory.application.proactive import (
    DeliveryQueueResult,
    DeliveryQueueStatus,
    ProactiveOutreachDispatcher,
    ProactiveOutreachLedger,
)
from longmemory.core.proactive import (
    OutreachPolicyConfig,
    OutreachPolicyState,
    OutreachState,
    OutreachTrigger,
    ProactivePolicySettings,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 4, 0, tzinfo=timezone.utc)


def setup_dispatcher(tmp_path, delivery):
    connection = open_database(tmp_path / "dispatch.db")
    initialize_schema(connection)
    ids = iter(f"id-{number}" for number in range(20))
    ledger = ProactiveOutreachLedger(
        SQLiteProactiveOutreachStore(connection), clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    dispatcher = ProactiveOutreachDispatcher(
        ledger, delivery_queue=delivery, clock=lambda: NOW,
    )
    return connection, ledger, dispatcher


def candidate(ledger, *, scheduled_for=NOW):
    return ledger.create_candidate(
        subject_id="user:self",
        trigger=OutreachTrigger.MANUAL_TEST,
        trigger_reason_code="synthetic_test",
        content="合成的主动问候。",
        scheduled_for=scheduled_for,
        expires_at=scheduled_for + timedelta(minutes=5),
        idempotency_key=f"test:{scheduled_for.isoformat()}",
    )


def settings(*, enabled=True, quiet_until=None):
    return ProactivePolicySettings(
        "user:self",
        OutreachPolicyConfig(enabled=enabled),
        quiet_until,
    )


def test_allowed_candidate_is_queued_once_without_claiming_playback(tmp_path):
    calls = []

    async def delivery(content, expires_at):
        calls.append((content, expires_at))
        return DeliveryQueueResult(DeliveryQueueStatus.ACCEPTED, "xiaozhi_queue_accepted")

    connection, ledger, dispatcher = setup_dispatcher(tmp_path, delivery)
    outreach = candidate(ledger)
    result = asyncio.run(dispatcher.dispatch(
        outreach.id, expected_revision=1, settings=settings(),
    ))

    assert result.outreach.state == OutreachState.QUEUED
    assert result.delivery.status == DeliveryQueueStatus.ACCEPTED
    assert calls == [(outreach.content, outreach.expires_at)]
    assert [event.new_state for event in ledger.list_events(outreach.id)] == [
        OutreachState.CANDIDATE, OutreachState.QUEUED,
    ]
    with pytest.raises(ValueError, match="outreach_dispatch_conflict"):
        asyncio.run(dispatcher.dispatch(
            outreach.id, expected_revision=1, settings=settings(),
        ))
    connection.close()


@pytest.mark.parametrize("outcome", ["rejected", "exception", "invalid_contract"])
def test_delivery_rejection_or_exception_is_audited_as_failed(tmp_path, outcome):
    async def delivery(_content, _expires_at):
        if outcome == "exception":
            raise RuntimeError("private upstream detail")
        if outcome == "invalid_contract":
            return None
        return DeliveryQueueResult(DeliveryQueueStatus.REJECTED, "device_offline")

    connection, ledger, dispatcher = setup_dispatcher(tmp_path, delivery)
    outreach = candidate(ledger)
    result = asyncio.run(dispatcher.dispatch(
        outreach.id, expected_revision=1, settings=settings(),
    ))

    assert result.outreach.state == OutreachState.FAILED
    assert result.outreach.failure_reason == (
        "device_offline" if outcome == "rejected" else "delivery_exception"
    )
    assert "private upstream detail" not in str(ledger.list_events(outreach.id))
    connection.close()


def test_policy_waits_or_blocks_without_calling_delivery(tmp_path):
    calls = []

    async def delivery(*values):
        calls.append(values)
        return DeliveryQueueResult(DeliveryQueueStatus.ACCEPTED, "unexpected")

    connection, ledger, dispatcher = setup_dispatcher(tmp_path, delivery)
    future = candidate(ledger, scheduled_for=NOW + timedelta(minutes=1))
    waiting = asyncio.run(dispatcher.dispatch(
        future.id, expected_revision=1, settings=settings(),
    ))
    assert waiting.outreach.state == OutreachState.CANDIDATE

    blocked_item = candidate(ledger, scheduled_for=NOW + timedelta(seconds=1))
    blocked = asyncio.run(dispatcher.dispatch(
        blocked_item.id,
        expected_revision=1,
        settings=settings(enabled=False),
    ))
    assert blocked.outreach.state == OutreachState.BLOCKED
    assert calls == []
    connection.close()


def test_persisted_quiet_setting_overrides_empty_runtime_state(tmp_path):
    async def delivery(*_values):
        raise AssertionError("quiet period must not deliver")

    connection, ledger, dispatcher = setup_dispatcher(tmp_path, delivery)
    outreach = candidate(ledger)
    result = asyncio.run(dispatcher.dispatch(
        outreach.id,
        expected_revision=1,
        settings=settings(quiet_until=NOW + timedelta(hours=1)),
        runtime_state=OutreachPolicyState(),
    ))
    assert result.outreach.state == OutreachState.BLOCKED
    assert result.decision.reason.value == "quiet_period"
    connection.close()
