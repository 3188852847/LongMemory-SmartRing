"""把小智连接缓存投影为主动策略需要的最小设备状态。"""

from longmemory.application.proactive.runtime_state import DeviceRuntimeState

from .xiaozhi import BridgeError, XiaozhiControlClient


class XiaozhiRuntimeStateProbe:
    def __init__(self, client: XiaozhiControlClient) -> None:
        self._client = client

    async def probe(self) -> DeviceRuntimeState:
        try:
            status = await self._client.status()
        except BridgeError as error:
            return DeviceRuntimeState(False, False, error.code)
        if not status["ready"] or not status["announcement_ready"]:
            return DeviceRuntimeState(
                False,
                status["user_session_active"],
                status.get("announcement_reason") or status.get("reason") or "device_not_ready",
            )
        return DeviceRuntimeState(True, status["user_session_active"])
