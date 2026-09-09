"""日常入口共享的常驻记忆运行时，不包含网页或小智协议。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import perf_counter
from uuid import uuid4

from longmemory.methods.contracts import (
    MemoryEvent,
    MemoryMethod,
    MemorySupport,
    ObservationResult,
    RetrievedTrace,
)
from longmemory.application.scenario_recall import ScenarioRecallItem, ScenarioRecallResult
from longmemory.application.persona_recall import PersonaRecallItem, PersonaRecallResult
from longmemory.application.natural_memory_commands import NaturalMemoryCommandResult
from longmemory.application.natural_companion_commands import NaturalCompanionCommandResult
from longmemory.application.follow_up_suggestions import FollowUpSuggestionResult
from longmemory.application.temporary_interaction import (
    TemporaryInteractionCommandResult,
    TemporaryInteractionDirective,
    TemporaryInteractionMode,
    TemporaryInteractionProvider,
    classify_next_turn_interaction,
    directive_context,
)
from longmemory.application.consolidation.scheduler import (
    LowFrequencyConsolidationScheduler,
)


@dataclass(frozen=True, slots=True)
class MemoryPreparationTimings:
    """记忆准备各阶段耗时；只记录时长，不携带用户内容或模型响应。"""

    lock_wait_ms: float
    command_ms: float
    observe_ms: float
    recall_ms: float
    scenario_ms: float
    persona_ms: float
    total_ms: float


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
    timings: MemoryPreparationTimings
    # 字段名为兼容既有 API 保留；它现在也可承载明确的陪伴控制命令。
    memory_command: (
        NaturalMemoryCommandResult
        | NaturalCompanionCommandResult
        | TemporaryInteractionCommandResult
        | None
    )
    follow_up_suggestion: FollowUpSuggestionResult | None = None
    temporary_interaction: TemporaryInteractionDirective | None = None


class MemoryRuntime:
    """持有一个长期存活的记忆方法实例，并安全服务多个入口线程。

    SQLite 连接本身不适合被多个线程同时操作，所以这里用互斥锁把一次
    observe/recall 或助手归档作为不可交错的运行时操作。模型生成不在锁内，
    因而慢模型不会阻塞另一入口读取记忆。
    """

    def __init__(self, database: Path, *, method: MemoryMethod, scenario_provider=None,
                 persona_provider=None, memory_command_handler=None,
                 temporary_interaction_provider: TemporaryInteractionProvider | None = None,
                 consolidation_scheduler: LowFrequencyConsolidationScheduler | None = None,
                 clock=None) -> None:
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
        self._temporary_interaction_provider = temporary_interaction_provider
        # “下一轮”是进程内、至多消费一次的会话控制，不进入长期记忆层。
        # 所有网页与圆屏入口共享同一个 Runtime，因此不会按入口各自残留。
        self._next_interaction: tuple[TemporaryInteractionMode, str, str] | None = None
        self._consolidation_scheduler = consolidation_scheduler
        self._clock = clock or (lambda: datetime.now(UTC))

    def prepare_user(self, text: str) -> PreparedMemoryTurn:
        started = perf_counter()
        event = MemoryEvent(str(uuid4()), "user", text, self._clock())
        lock_started = perf_counter()
        with self._lock:
            lock_acquired = perf_counter()
            self._ensure_open()
            command_started = perf_counter()
            command = None
            next_selection = classify_next_turn_interaction(text)
            if next_selection is not None:
                if next_selection == "cancel":
                    had_pending = self._next_interaction is not None
                    self._next_interaction = None
                    command = TemporaryInteractionCommandResult(
                        "cancel_next_interaction",
                        "applied" if had_pending else "not_armed",
                        (
                            "好的，已取消下一轮的临时互动方式。"
                            if had_pending else
                            "当前没有等待生效的下一轮互动方式，因此没有改动。"
                        ),
                        None,
                    )
                else:
                    self._next_interaction = (
                        next_selection, event.event_id, event.content,
                    )
                    notices = {
                        "listen_only": "好的，下一轮我会先听你说，不主动给建议。",
                        "ask_before_advice": "好的，下一轮我会先听你说，再问你是否需要建议。",
                        "direct_advice": "好的，下一轮我会直接给出简洁、可执行的建议。",
                    }
                    command = TemporaryInteractionCommandResult(
                        "set_next_interaction", "armed",
                        notices[next_selection], next_selection,
                    )
            elif self._memory_command_handler is not None:
                companion_handler = getattr(
                    self._memory_command_handler, "handle_companion", None,
                )
                if companion_handler is not None:
                    command = companion_handler(event)
                if command is None:
                    memory_handler = getattr(
                        self._memory_command_handler, "handle_memory",
                        None,
                    )
                    if memory_handler is not None:
                        command = memory_handler(
                            event, write_enabled=self._write_enabled,
                        )
                    elif self._write_enabled:
                        command = self._memory_command_handler.handle(event)
            command_finished = perf_counter()
            observe_started = perf_counter()
            if isinstance(command, TemporaryInteractionCommandResult):
                # 一次性设置句是控制证据，只保留 L0，不能被规则或 LLM
                # 提取器误写成长期用户偏好。
                observation = self._method.archive(event)
            elif command is not None:
                observation = ObservationResult(event.event_id, command.writes)
            else:
                observation = (self._method.observe(event) if self._write_enabled
                               else self._method.archive(event))
            observe_finished = perf_counter()
            follow_up_suggestion = None
            if command is None and observation.writes:
                suggester = getattr(
                    self._memory_command_handler, "suggest_follow_up", None,
                )
                if suggester is not None:
                    follow_up_suggestion = suggester(event, observation.writes)
            recall_started = perf_counter()
            support = (
                self._method.recall(text)
                if self._use_enabled
                else MemorySupport(str(uuid4()), "", (), "disabled_by_user", None)
            )
            recall_finished = perf_counter()
            scenario_started = perf_counter()
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
            scenario_finished = perf_counter()
            persona_started = perf_counter()
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
            persona_finished = perf_counter()
            temporary_interaction = None
            interaction_strategy = "temporary_interaction_v1"
            if command is None and self._next_interaction is not None:
                mode, source_message_id, source_content = self._next_interaction
                # 在进入模型调用前原子消费，失败或中断也不会在之后重复套用。
                self._next_interaction = None
                temporary_interaction = TemporaryInteractionDirective(
                    mode=mode,
                    source_memory_id=None,
                    source_content=source_content,
                    source_message_id=source_message_id,
                    valid_to=None,
                    context=directive_context(mode),
                    scope="next_turn",
                )
                interaction_strategy = "temporary_interaction_next_turn_v1"
            elif (
                command is None and self._use_enabled
                and self._temporary_interaction_provider is not None
            ):
                temporary_interaction = self._temporary_interaction_provider.current(
                    at=event.occurred_at,
                )
            if temporary_interaction is not None:
                combined = "\n\n".join(value for value in (
                    support.context, temporary_interaction.context,
                ) if value)
                retrieved = tuple(support.retrieved or ())
                if (
                    temporary_interaction.source_memory_id is not None
                    and not any(
                        item.item_id == temporary_interaction.source_memory_id
                        for item in retrieved
                    )
                ):
                    retrieved += (RetrievedTrace(
                        temporary_interaction.source_memory_id,
                        temporary_interaction.source_content,
                        (temporary_interaction.source_message_id,),
                    ),)
                strategy = "+".join(value for value in (
                    support.retrieval_strategy, interaction_strategy,
                ) if value)
                support = MemorySupport(
                    support.call_id, combined, retrieved,
                    strategy, support.warning_code,
                )
            if command is not None:
                if isinstance(command, TemporaryInteractionCommandResult):
                    label = "[互动设置结果]"
                elif isinstance(command, NaturalCompanionCommandResult):
                    label = "[陪伴设置结果]"
                else:
                    label = "[记忆操作结果]"
                operation_context = label + "\n" + command.notice
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
        finished = perf_counter()
        timings = MemoryPreparationTimings(
            lock_wait_ms=round((lock_acquired - lock_started) * 1000, 3),
            command_ms=round((command_finished - command_started) * 1000, 3),
            observe_ms=round((observe_finished - observe_started) * 1000, 3),
            recall_ms=round((recall_finished - recall_started) * 1000, 3),
            scenario_ms=round((scenario_finished - scenario_started) * 1000, 3),
            persona_ms=round((persona_finished - persona_started) * 1000, 3),
            total_ms=round((finished - started) * 1000, 3),
        )
        # 通知发生在 SQLite 互斥锁之外；它只唤醒后台线程，不让聊天等待整理。
        if observation.writes and self._consolidation_scheduler is not None:
            self._consolidation_scheduler.notify_new_evidence()
        return PreparedMemoryTurn(
            event, observation, support, write_enabled, use_enabled,
            scenario_use_enabled, scenario_result.items,
            persona_use_enabled, persona_result.items, timings, command,
            follow_up_suggestion, temporary_interaction,
        )

    def record_assistant(self, text: str) -> ObservationResult:
        event = MemoryEvent(str(uuid4()), "assistant", text, self._clock())
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
                "temporary_interaction_available": (
                    self._temporary_interaction_provider is not None
                ),
                "next_interaction_armed": self._next_interaction is not None,
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
