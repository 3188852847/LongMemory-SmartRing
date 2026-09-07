"""控制台进程拥有的低频主动问候循环。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable


LOGGER = logging.getLogger(__name__)


class ProactiveScheduleLoop:
    """每隔短时间评估精确分钟；幂等和是否发送仍由应用层决定。"""

    def __init__(self, tick: Callable[[], Awaitable[object]], *, interval_seconds=15):
        if not 5 <= interval_seconds <= 60:
            raise ValueError("proactive_schedule_interval_invalid")
        self._tick = tick
        self._interval = interval_seconds
        self._stop = asyncio.Event()
        self._task = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("proactive_schedule_already_started")
        self._task = asyncio.create_task(self._run(), name="proactive-schedule")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                # 不把正文或第三方异常写入日志；下一次只重新评估时间条件，
                # 已创建候选由数据库幂等键保证绝不重复投递。
                LOGGER.warning("proactive_schedule_tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
