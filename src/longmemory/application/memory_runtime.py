"""日常入口共享的常驻记忆运行时，不包含网页或小智协议。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from longmemory.methods.contracts import MemoryEvent, MemorySupport, ObservationResult
from longmemory.methods.longmemory_v1.method import LongMemoryV1


@dataclass(frozen=True, slots=True)
class PreparedMemoryTurn:
    """一次用户输入的实际写入与召回结果，供不同入口统一消费。"""

    event: MemoryEvent
    observation: ObservationResult
    support: MemorySupport
    write_enabled: bool
    use_enabled: bool


class MemoryRuntime:
    """持有一个长期存活的记忆方法实例，并安全服务多个入口线程。

    SQLite 连接本身不适合被多个线程同时操作，所以这里用互斥锁把一次
    observe/recall 或助手归档作为不可交错的运行时操作。模型生成不在锁内，
    因而慢模型不会阻塞另一入口读取记忆。
    """

    def __init__(self, database: Path, *, method=None) -> None:
        self.database = database.resolve()
        self._method = method if method is not None else LongMemoryV1(
            self.database, existing_only=True, allow_cross_thread=True,
        )
        self._lock = RLock()
        self._closed = False
        self._write_enabled = True
        self._use_enabled = True

    def prepare_user(self, text: str) -> PreparedMemoryTurn:
        event = MemoryEvent(str(uuid4()), "user", text, datetime.now(UTC))
        with self._lock:
            self._ensure_open()
            observation = (
                self._method.observe(event)
                if self._write_enabled
                else self._method.archive(event)
            )
            support = (
                self._method.recall(text)
                if self._use_enabled
                else MemorySupport(str(uuid4()), "", (), "disabled_by_user", None)
            )
            write_enabled = self._write_enabled
            use_enabled = self._use_enabled
        return PreparedMemoryTurn(event, observation, support, write_enabled, use_enabled)

    def record_assistant(self, text: str) -> ObservationResult:
        event = MemoryEvent(str(uuid4()), "assistant", text, datetime.now(UTC))
        with self._lock:
            self._ensure_open()
            return self._method.observe(event)

    def status(self) -> dict:
        with self._lock:
            self._ensure_open()
            self._method.wait_until_ready()
            return {
                "ready": True,
                "method": self._method.name,
                "implementation_version": self._method.implementation_version,
                "retrieval": getattr(self._method, "retrieval_name", "unknown"),
                "database": str(self.database),
                "write_enabled": self._write_enabled,
                "use_enabled": self._use_enabled,
                "settings_persistent": False,
            }

    def configure(self, *, write_enabled: bool, use_enabled: bool) -> dict:
        """原子更新运行期模式；重启恢复默认开启，不写数据库或配置文件。"""

        if type(write_enabled) is not bool or type(use_enabled) is not bool:
            raise ValueError("memory_mode_invalid")
        with self._lock:
            self._ensure_open()
            self._write_enabled = write_enabled
            self._use_enabled = use_enabled
            return self.status()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._method.close()
                self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("记忆运行时已经关闭。")
