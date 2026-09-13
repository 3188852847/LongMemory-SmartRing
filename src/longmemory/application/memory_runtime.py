"""日常入口共享的常驻记忆运行时，不包含网页或小智协议。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
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
                 l2_sufficiency_shadow=None,
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
        # 影子观察器只接收当前轮候选快照并在后台写审计；它没有修改
        # ``support`` 的接口，因此即使启用也不能放行或拦截正式回答。
        self._l2_sufficiency_shadow = l2_sufficiency_shadow
        self._clock = clock or (lambda: datetime.now(UTC))
        # 单工作线程保证候选模型不会并发轰击供应商。任务只由圆屏完成回执
        # 触发，Runtime 关闭时会等待它收尾，再关闭 SQLite 连接。
        self._deferred_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="longmemory-l1",
        )
        self._deferred_events: dict[str, MemoryEvent] = {}
        self._deferred_futures: set[Future] = set()
        self._deferred_last_result = {"state": "not_run", "warning_code": None}
        self._closing = False

    def prepare_user(
        self, text: str, *, defer_slow_observation: bool = False,
    ) -> PreparedMemoryTurn:
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
            elif (
                defer_slow_observation
                and self._write_enabled
                and self._method.capabilities.deferred_observation
            ):
                # 本轮回答不需要等模型把“当前这句话”派生为 L1；先保存
                # L0，再用此前已经完成的记忆召回。回答完成回执会触发补写。
                observation = self._method.archive(event)
                self._deferred_events[event.event_id] = event
                observation = ObservationResult(
                    event.event_id, (), processing_status="source_only",
                    warning_code="l1_extraction_deferred",
                )
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
            shadow_scenario_result = scenario_result
            if (self._use_enabled and self._l2_sufficiency_shadow is not None
                    and self._scenario_provider is not None
                    and not self._scenario_use_enabled):
                # 正式 L2 关闭时仍可旁路观测同一个召回器；结果不会进入
                # ``support.context``，因此个人体验与当前策略完全一致。
                try:
                    shadow_scenario_result = self._scenario_provider.recall(text)
                except Exception:
                    # 这是明确的旁路边界：影子读取失败只丢失一条研究样本，
                    # 不能把原本不使用 L2 的正式回答变成失败。
                    shadow_scenario_result = None
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
        if (command is None and use_enabled and shadow_scenario_result is not None
                and self._l2_sufficiency_shadow is not None):
            try:
                self._l2_sufficiency_shadow.submit(
                    user_message_id=event.event_id,
                    query=text,
                    candidates=shadow_scenario_result,
                )
            except Exception:
                # 提交器关闭或旁路队列异常同样不改变本轮返回值。
                pass
        return PreparedMemoryTurn(
            event, observation, support, write_enabled, use_enabled,
            scenario_use_enabled, scenario_result.items,
            persona_use_enabled, persona_result.items, timings, command,
            follow_up_suggestion, temporary_interaction,
        )

    def complete_deferred_observation(self, event_id: str) -> bool:
        """把已完成回答对应的 L1 派生交给受管队列；重复回执不重复提交。"""

        with self._lock:
            self._ensure_open()
            event = self._deferred_events.pop(event_id, None)
            if event is None or self._closing:
                return False
            future = self._deferred_executor.submit(
                self._run_deferred_observation, event,
            )
            self._deferred_futures.add(future)
            self._deferred_last_result = {"state": "running", "warning_code": None}
            future.add_done_callback(self._deferred_done)
            return True

    def retry_failed_observation(
        self, source_message_id: str, *, expected_attempt_id: str,
    ) -> dict:
        """显式重跑一个失败/中断的 L1 派生；只排队一次，不复制 L0。"""

        with self._lock:
            self._ensure_open()
            if self._closing:
                raise ValueError("l1_retry_runtime_closing")
            if not self._method.capabilities.failed_observation_recovery:
                raise ValueError("l1_retry_method_unsupported")
            prepare = getattr(
                self._method, "prepare_failed_observation_recovery", None,
            )
            if prepare is None:
                raise ValueError("l1_retry_method_unsupported")
            event, attempt_id = prepare(
                source_message_id, expected_attempt_id=expected_attempt_id,
            )
            future = self._deferred_executor.submit(
                self._run_deferred_observation, event, False,
            )
            self._deferred_futures.add(future)
            self._deferred_last_result = {"state": "running", "warning_code": None}
            future.add_done_callback(self._deferred_done)
            return {
                "state": "queued", "source_message_id": source_message_id,
                "attempt_id": attempt_id,
            }

    def _run_deferred_observation(
        self, event: MemoryEvent, start_audit: bool = True,
    ) -> ObservationResult:
        # 网络模型调用不持 Runtime 锁；网页查看、设备召回和状态读取不会
        # 因 2–5 秒的候选生成而一起卡住。只有最终 SQLite 补写需要互斥。
        extracted = self._method.extract_archived(
            event, start_audit=start_audit,
        )
        if isinstance(extracted, ObservationResult):
            return extracted
        with self._lock:
            self._ensure_open()
            observation = self._method.persist_archived(event, extracted)
            if observation.writes:
                suggester = getattr(
                    self._memory_command_handler, "suggest_follow_up", None,
                )
                if suggester is not None:
                    suggester(event, observation.writes)
        if observation.writes and self._consolidation_scheduler is not None:
            self._consolidation_scheduler.notify_new_evidence()
        return observation

    def _deferred_done(self, future: Future) -> None:
        try:
            result = future.result()
        except BaseException:
            # 状态只暴露稳定代码，不泄漏模型、数据库或用户正文。
            last_result = {
                "state": "failed", "warning_code": "deferred_observation_failed",
            }
        else:
            last_result = {
                "state": (
                    "completed" if result.processing_status == "completed" else "failed"
                ),
                "warning_code": result.warning_code,
            }
        with self._lock:
            self._deferred_futures.discard(future)
            self._deferred_last_result = last_result

    def wait_for_deferred_observations(self) -> None:
        """等待已提交任务，供停机收尾、诊断和确定性测试使用。"""

        while True:
            with self._lock:
                futures = tuple(self._deferred_futures)
            if not futures:
                return
            for future in futures:
                future.result()

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
                "deferred_observation": {
                    "supported": self._method.capabilities.deferred_observation,
                    "awaiting_completion": len(self._deferred_events),
                    "running_or_queued": len(self._deferred_futures),
                    "last_result": dict(self._deferred_last_result),
                },
                "consolidation_scheduler": (
                    self._consolidation_scheduler.status().to_dict()
                    if self._consolidation_scheduler is not None
                    else {"enabled": False, "available": False}
                ),
                "l2_sufficiency_shadow": (
                    self._l2_sufficiency_shadow.status().to_dict()
                    if self._l2_sufficiency_shadow is not None
                    else {"enabled": False, "state": "disabled"}
                ),
            }

    def wait_for_l2_sufficiency_shadow(self) -> None:
        """等待旁路任务，供测试和受控停机使用；正式聊天不调用。"""

        if self._l2_sufficiency_shadow is not None:
            self._l2_sufficiency_shadow.wait()

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
        # 不能在持锁状态 shutdown：正在完成模型调用的工作线程随后还需
        # 取得同一把锁写入 SQLite，否则会形成停机死锁。
        with self._lock:
            if self._closed or self._closing:
                return
            self._closing = True
            self._deferred_events.clear()
        self._deferred_executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            if not self._closed:
                try:
                    if self._l2_sufficiency_shadow is not None:
                        self._l2_sufficiency_shadow.close()
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
