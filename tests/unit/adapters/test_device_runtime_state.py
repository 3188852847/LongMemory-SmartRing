import asyncio

from longmemory.adapters.device_control.runtime_state import XiaozhiRuntimeStateProbe
from longmemory.adapters.device_control.xiaozhi import BridgeError


class Client:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    async def status(self):
        if self.error:
            raise self.error
        return self.value


def test_busy_device_is_not_ready_and_marks_active_session():
    probe = XiaozhiRuntimeStateProbe(Client({
        "ready": True, "announcement_ready": False,
        "user_session_active": True, "announcement_reason": "device_busy",
    }))
    state = asyncio.run(probe.probe())
    assert state.ready is False and state.user_session_active is True
    assert state.reason_code == "device_busy"


def test_bridge_failure_is_not_invented_as_user_activity():
    probe = XiaozhiRuntimeStateProbe(
        Client(error=BridgeError("bridge_unavailable")),
    )
    state = asyncio.run(probe.probe())
    assert state.ready is False and state.user_session_active is False
    assert state.reason_code == "bridge_unavailable"


def test_ready_device_has_no_failure_reason():
    probe = XiaozhiRuntimeStateProbe(Client({
        "ready": True, "announcement_ready": True, "user_session_active": False,
    }))
    state = asyncio.run(probe.probe())
    assert state.ready is True and state.reason_code is None
