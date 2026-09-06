"""日常入口共享的常驻记忆运行时，不包含网页或小智协议。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from longmemory.methods.contracts import (
    MemoryEvent,
    MemoryMethod,
    MemorySupport,
    ObservationResult,
)
from longmemory.application.scenario_recall import ScenarioRecallItem, ScenarioRecallResult
from longmemory.application.persona_recall import PersonaRecallItem, PersonaRecallResult
from longmemory.application.natural_memory_commands import NaturalMemoryCommandResult
from longmemory.application.consolidation.scheduler import (
    LowFrequencyConsolidationScheduler,
)


@dataclass(frozen=True, slots=True)
class PreparedMemoryTurn:
    """一次用户输入的实际写入与召回结果，供不同入口统一消费。"""

    event: MemoryEvent
    observation: ObservationResult
    support: MemorySupport
    write_enabled: bool
    use_enabled: bool
    scenario_use_enabled: bool
    scenarios: tuple[ScenarioRecallItem, ...]
    persona_use_enabled: bool
    personas: tuple[PersonaRecallItem, ...]
    memory_command: NaturalMemoryCommandResult | None


class MemoryRuntime:
    """持有一个长期存活的记忆方法实例，并安全服务多个入口线程。

    SQLite 连接本身不适合被多个线程同时操作，所以这里用互斥锁把一次
    observe/recall 或助手归档作为不可交错的运行时操作。模型生成不在锁内，
    因而慢模型不会阻塞另一入口读取记忆。
    """

    def __init__(self, database: Path, *, method: MemoryMethod, scenario_provider=None,
                 persona_provider=None, memory_command_handler=None,
                 consolidation_scheduler: LowFrequencyConsolidationScheduler | None = None) -> None:
        self.database = database.resolve()
        # Runtime 只编排统一方法契约。具体使用规则、LLM 提取还是其他方法，
        # 必须由进程入口的装配层决定，不能在应用层偷偷选择实现。
        self._method = method
        self._lock = RLock()
        self._closed = False
        self._write_enabled = True
        self._use_enabled = True
        self._scenario_provider = scenario_provider
        # L2 刚进入真实回答链，默认关闭，避免升级后无提示改变既有行为。
        self._scenario_use_enabled = False
        self._persona_provider = persona_provider
        self._persona_use_enabled = False
        self._memory_command_handler = memory_command_handler
        self._consolidation_scheduler = consolidation_scheduler

    def prepare_user(self, text: str) -> PreparedMemoryTurn:
        event = MemoryEvent(str(uuid4()), "user", text, datetime.now(UTC))
        with self._lock:
            self._ensure_open()
            command = None
            if self._write_enabled and self._memory_command_handler is not None:
                command = self._memory_command_handler.handle(event)
            if command is not None:
                observation = ObservationResult(event.event_id, command.writes)
            else:
                observation = (self._method.observe(event) if self._write_enabled
                               else self._method.archive(event))
            support = (
                self._method.recall(text)
                if self._use_enabled
                else MemorySupport(str(uuid4()), "", (), "disabled_by_user", None)
            )
            scenario_result = ScenarioRecallResult("", ())
            if self._use_enabled and self._scenario_use_enabled and self._scenario_provider:
                scenario_result = self._scenario_provider.recall(text)
                if scenario_result.context:
                    combined = "\n\n".join(value for value in (support.context, scenario_result.context) if value)
                    strategy = "+".join(value for value in (
                        support.retrieval_strategy, scenario_result.strategy
                    ) if value)
                    support = MemorySupport(
                        support.call_id, combined, support.retrieved,
                        strategy, support.warning_code,
                    )
            persona_result = PersonaRecallResult("", ())
            if self._use_enabled and self._persona_use_enabled and self._persona_provider:
                persona_result = self._persona_provider.recall(text)
                if persona_result.context:
                    combined = "\n\n".join(
                        value for value in (support.context, persona_result.context) if value
                    )
                    strategy = "+".join(value for value in (
                        support.retrieval_strategy, persona_result.strategy
                    ) if value)
                    support = MemorySupport(
                        support.call_id, combined, support.retrieved,
                        strategy, support.warning_code,
                    )
            if command is not None:
                operation_context = "[记忆操作结果]\n" + command.notice
                combined = "\n\n".join(
                    value for value in (operation_context, support.context) if value
                )
                support = MemorySupport(
                    support.call_id, combined, support.retrieved,
                    support.retrieval_strategy, support.warning_code,
                )
            write_enabled = self._write_enabled
            use_enabled = self._use_enabled
            scenario_use_enabled = self._scenario_use_enabled
            persona_use_enabled = self._persona_use_enabled
        # 通知发生在 SQLite 互斥锁之外；它只唤醒后台线程，不让聊天等待整理。
        if observation.writes and self._consolidation_scheduler is not None:
            self._consolidation_scheduler.notify_new_evidence()
        return PreparedMemoryTurn(
            event, observation, support, write_enabled, use_enabled,
            scenario_use_enabled, scenario_result.items,
            persona_use_enabled, persona_result.items, command,
        )

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
                "scenario_use_enabled": self._scenario_use_enabled,
                "scenario_available": self._scenario_provider is not None,
                "persona_use_enabled": self._persona_use_enabled,
                "persona_available": self._persona_provider is not None,
                "settings_persistent": False,
                "consolidation_scheduler": (
                    self._consolidation_scheduler.status().to_dict()
                    if self._consolidation_scheduler is not None
                    else {"enabled": False, "available": False}
                ),
            }

    def configure(self, *, write_enabled: bool, use_enabled: bool,
                  scenario_use_enabled: bool | None = None,
                  persona_use_enabled: bool | None = None) -> dict:
        """原子更新运行期模式；重启恢复默认开启，不写数据库或配置文件。"""

        if (type(write_enabled) is not bool or type(use_enabled) is not bool
                or (scenario_use_enabled is not None and type(scenario_use_enabled) is not bool)
                or (persona_use_enabled is not None and type(persona_use_enabled) is not bool)):
            raise ValueError("memory_mode_invalid")
        with self._lock:
            self._ensure_open()
            if scenario_use_enabled and self._scenario_provider is None:
                raise ValueError("scenario_memory_unavailable")
            if persona_use_enabled and self._persona_provider is None:
                raise ValueError("persona_memory_unavailable")
            self._write_enabled = write_enabled
            self._use_enabled = use_enabled
            if scenario_use_enabled is not None:
                self._scenario_use_enabled = scenario_use_enabled
            if persona_use_enabled is not None:
                self._persona_use_enabled = persona_use_enabled
            return self.status()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                try:
                    if self._consolidation_scheduler is not None:
                        self._consolidation_scheduler.close()
                    self._method.close()
                finally:
                    if self._scenario_provider is not None:
                        self._scenario_provider.close()
                    if self._persona_provider is not None:
                        self._persona_provider.close()
                    if self._memory_command_handler is not None:
                        self._memory_command_handler.close()
                    self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("记忆运行时已经关闭。")
