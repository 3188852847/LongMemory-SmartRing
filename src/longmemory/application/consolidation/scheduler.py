"""日常记忆运行时拥有的唯一低频整理调度器。"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Event, Lock, Thread, current_thread


@dataclass(frozen=True, slots=True)
class ConsolidationSchedulerStatus:
    """只暴露运行元数据，不包含记忆正文或模型响应。"""

    enabled: bool
    running: bool
    pending: bool
    closed: bool
    completed_cycle_count: int
    failed_cycle_count: int
    last_outcome: str | None
    last_finished_at: datetime | None

    def to_dict(self) -> dict:
        payload = asdict(self)
        if self.last_finished_at is not None:
            payload["last_finished_at"] = self.last_finished_at.isoformat()
        return payload


class LowFrequencyConsolidationScheduler:
    """合并频繁通知，并在一个守护线程中串行执行低频整理。

    ``run_cycle`` 必须为每轮自行打开和关闭数据库/模型资源，不能复用聊天
    运行时的 SQLite 连接。默认关闭时不创建线程，也不扫描数据库。
    """

    def __init__(
        self,
        *,
        subject_id: str,
        run_cycle: Callable[[str], str | None],
        enabled: bool = False,
    ) -> None:
        if not subject_id.strip():
            raise ValueError("consolidation_scheduler_subject_required")
        self._subject_id = subject_id
        self._run_cycle = run_cycle
        self._enabled = enabled
        self._wake = Event()
        self._stop = Event()
        self._lock = Lock()
        self._running = False
        self._pending = False
        self._closed = False
        self._completed = 0
        self._failed = 0
        self._last_outcome: str | None = None
        self._last_finished_at: datetime | None = None
        self._thread: Thread | None = None
        if enabled:
            self._thread = Thread(
                target=self._worker,
                name="longmemory-consolidation",
                daemon=True,
            )
            self._thread.start()

    def notify_new_evidence(self) -> bool:
        """常数时间发送信号；多次通知会合并，不在聊天线程执行整理。"""

        with self._lock:
            if not self._enabled or self._closed:
                return False
            self._pending = True
            self._wake.set()
            return True

    def status(self) -> ConsolidationSchedulerStatus:
        with self._lock:
            return ConsolidationSchedulerStatus(
                enabled=self._enabled,
                running=self._running,
                pending=self._pending,
                closed=self._closed,
                completed_cycle_count=self._completed,
                failed_cycle_count=self._failed,
                last_outcome=self._last_outcome,
                last_finished_at=self._last_finished_at,
            )

    def close(self, *, timeout: float = 2.0) -> bool:
        """停止接收通知并限时等待；返回后台线程是否已经退出。"""

        if timeout < 0:
            raise ValueError("consolidation_scheduler_timeout_invalid")
        with self._lock:
            if self._closed:
                thread = self._thread
            else:
                self._closed = True
                self._pending = False
                self._stop.set()
                self._wake.set()
                thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def _worker(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                return
            with self._lock:
                if not self._pending:
                    continue
                self._pending = False
                self._running = True
            failed = False
            try:
                outcome = self._run_cycle(self._subject_id) or "completed"
            except Exception:
                # 这里只保存稳定状态，具体异常由 run_cycle 自己写入安全日志/账本。
                outcome = "cycle_failed"
                failed = True
            finally:
                with self._lock:
                    self._running = False
                    self._last_outcome = outcome
                    self._last_finished_at = datetime.now(UTC)
                    if failed:
                        self._failed += 1
                    else:
                        self._completed += 1
