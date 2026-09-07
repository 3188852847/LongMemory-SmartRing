import asyncio
from datetime import datetime, timedelta, timezone

from longmemory.application.proactive import (
    DeviceRuntimeState,
    ProactiveRuntimeStateService,
)
from longmemory.core.proactive import OutreachPolicyState


NOW = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)


class History:
    def __init__(self):
        self.calls = []

    def read(self, subject_id, *, now):
        self.calls.append((subject_id, now))
        return OutreachPolicyState(
            attempted_at=(NOW - timedelta(hours=1),),
            awaiting_user_response=True,
        )


def test_runtime_service_combines_history_with_live_session_only():
    history = History()

    async def probe():
        return DeviceRuntimeState(False, True, "device_busy")

    service = ProactiveRuntimeStateService(
        history, device_probe=probe, clock=lambda: NOW,
    )
    snapshot = asyncio.run(service.snapshot("user:self"))
    assert snapshot.policy_state.attempted_at == (NOW - timedelta(hours=1),)
    assert snapshot.policy_state.awaiting_user_response is True
    assert snapshot.policy_state.user_session_active is True
    assert snapshot.device.reason_code == "device_busy"
    assert history.calls == [("user:self", NOW)]
