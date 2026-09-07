"""汇总主动许可所需的可信事实，不读取记忆正文或调用模型。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from longmemory.core.proactive import OutreachPolicyState


class ProactiveHistoryReader(Protocol):
    def read(self, subject_id: str, *, now: datetime) -> OutreachPolicyState: ...


@dataclass(frozen=True, slots=True)
class DeviceRuntimeState:
    ready: bool
    user_session_active: bool
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.ready and self.reason_code is not None:
            raise ValueError("device_runtime_ready_reason_unexpected")
        if self.reason_code is not None and (
            self.reason_code != self.reason_code.strip()
            or not 1 <= len(self.reason_code) <= 120
        ):
            raise ValueError("device_runtime_reason_invalid")


DeviceRuntimeProbe = Callable[[], Awaitable[DeviceRuntimeState]]


@dataclass(frozen=True, slots=True)
class ProactiveRuntimeSnapshot:
    policy_state: OutreachPolicyState
    device: DeviceRuntimeState


class ProactiveRuntimeStateService:
    """组合持久历史和瞬时设备状态；不把设备离线伪装成用户忙碌。"""

    def __init__(
        self,
        history: ProactiveHistoryReader,
        *,
        device_probe: DeviceRuntimeProbe,
        clock: Callable[[], datetime],
    ) -> None:
        self._history = history
        self._device_probe = device_probe
        self._clock = clock

    async def snapshot(self, subject_id: str) -> ProactiveRuntimeSnapshot:
        now = self._clock()
        history = self._history.read(subject_id, now=now)
        device = await self._device_probe()
        return ProactiveRuntimeSnapshot(
            OutreachPolicyState(
                attempted_at=history.attempted_at,
                awaiting_user_response=history.awaiting_user_response,
                user_session_active=device.user_session_active,
                quiet_until=history.quiet_until,
            ),
            device,
        )
