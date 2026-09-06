import asyncio
from datetime import datetime, timezone

from longmemory.adapters.device_control.proactive_delivery import (
    XiaozhiProactiveDelivery,
)
from longmemory.adapters.device_control.xiaozhi import BridgeError
from longmemory.application.proactive import DeliveryQueueStatus


EXPIRES_AT = datetime(2026, 9, 6, 12, 5, tzinfo=timezone.utc)


class Client:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def announce(self, content, expires_at):
        self.calls.append((content, expires_at))
        if self.error:
            raise self.error
        return {"state": "queued"}


def test_xiaozhi_queue_acceptance_remains_only_queued():
    client = Client()
    adapter = XiaozhiProactiveDelivery(client)
    result = asyncio.run(adapter.queue("合成问候。", EXPIRES_AT))
    assert result.status == DeliveryQueueStatus.ACCEPTED
    assert result.reason_code == "xiaozhi_queue_accepted"
    assert client.calls == [("合成问候。", EXPIRES_AT)]


def test_xiaozhi_stable_failure_reason_is_preserved():
    client = Client(BridgeError("device_busy", 409))
    result = asyncio.run(
        XiaozhiProactiveDelivery(client).queue("合成问候。", EXPIRES_AT)
    )
    assert result.status == DeliveryQueueStatus.FAILED
    assert result.reason_code == "device_busy"
