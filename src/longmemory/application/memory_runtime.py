"""日常入口共享的常驻记忆运行时，不包含网页或小智协议。"""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from time import perf_counter
from uuid import uuid4
import re
import json
import logging
from hashlib import sha256
from longmemory.application.round_screen_turns import memory_receipt, validate_receipt, PlatformTurnCompletion
from longmemory.application.round_screen_memory_feedback import classify_explicit_round_screen_feedback

from longmemory.methods.contracts import (
    MemoryEvent,
    MemoryMethod,
    MemorySupport,
    MemoryReadBusyError,
    ObservationResult,
    require_management,
)
from longmemory.application.natural_memory_commands import NaturalMemoryCommandResult
from longmemory.application.temporary_interaction import (
    TemporaryInteractionCommandResult,
    TemporaryInteractionDirective,
    TemporaryInteractionMode,
    classify_next_turn_interaction,
    directive_context,
)


_LOGGER = logging.getLogger(__name__)


def _emit_round_screen_timing(round_id, started, acquired, status, callback=None):
    """外层锁等待原来不在 prepare 时钟内；独立日志保留旧协议和时钟语义。"""
    payload = {'version': 1, 'round_id': round_id if isinstance(round_id, str)
        and re.fullmatch(r'[0-9a-f]{24,32}', round_id) else None, 'status': status,
        'timings_ms': {'outer_lock_wait_ms': None if acquired is None else round(max(0, acquired - started) * 1000, 3),
                       'total_ms': round(max(0, perf_counter() - started) * 1000, 3)}}
    try:
        _LOGGER.info('round_screen_entry_timing=%s', json.dumps(payload, sort_keys=True))
    except Exception:
        pass  # 观测不能阻断来源持久化或把原异常替换为日志异常。
    if callback is not None:
        try: callback(payload)
        except Exception: pass


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
    timings: MemoryPreparationTimings
    # 字段名为兼容既有 API 保留；它现在也可承载明确的陪伴控制命令。
    memory_command: (
        NaturalMemoryCommandResult
        | TemporaryInteractionCommandResult
        | None
    )
    temporary_interaction: TemporaryInteractionDirective | None = None


class MemoryRuntime:
    """串行管理网页和圆屏共用的引擎实例、来源账本与后台投递队列。"""

    def __init__(self, database: Path, *, method: MemoryMethod, memory_command_handler=None,
                 clock=None, backend_assembly=None, round_screen_store=None,
                 state_identity=None) -> None:
        self.database = database.resolve()
        self._method = method
        self._round_screen_store = round_screen_store
        self.backend_assembly = backend_assembly
        self._state_identity = state_identity
        self._model_service = None
        self._lock = RLock()
        self._closed = False
        self._write_enabled = True
        # 后台同步抛错时结果未知，前台的暂停状态不能充当后台回执。
        self._confirmed_background_write_enabled: bool | None = None
        self._use_enabled = True
        # 候选票据只在本Runtime实例和当前设置版本内有效，重启不能复用旧版本。
        from secrets import token_hex
        self._proposal_instance = token_hex(16)
        self._proposal_revision = 0
        self._proposal_formal = {}
        self._memory_command_handler = memory_command_handler
        # “下一轮”是进程内、至多消费一次的会话控制，不进入长期记忆层。
        # 所有网页与圆屏入口共享同一个 Runtime，因此不会按入口各自残留。
        self._next_interaction: tuple[TemporaryInteractionMode, str, str] | None = None
        self._clock = clock or (lambda: datetime.now(UTC))
        # Hy的持久后台队列与平台前台写门保持一致；旧方法没有此能力则不接管。
        # 初始化失败前不创建本Runtime的工作线程，避免留下无人拥有的执行器。
        self._sync_background_writes(self._write_enabled)
        # 单工作线程保证候选模型不会并发轰击供应商。任务只由圆屏完成回执
        # 触发，Runtime 关闭时会等待它收尾，再关闭 SQLite 连接。
        self._deferred_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="hy-observation",
        )
        self._deferred_events: dict[str, MemoryEvent] = {}
        self._deferred_futures: set[Future] = set()
        self._deferred_last_result = {"state": "not_run", "warning_code": None}
        self._closing = False

    def import_dialogue(self, rows):
        """导入已绑定 QQ 窗口中过去的原话，仅归档，不触发提取、召回或回复。"""
        events = tuple(rows)
        for event in events:
            if (not isinstance(event, MemoryEvent) or event.role not in {"user", "assistant"}
                    or not isinstance(event.event_id, str) or not event.event_id.startswith("qq-history:")
                    or not isinstance(event.content, str) or not event.content.strip()
                    or not isinstance(event.session_id, str) or not re.fullmatch(r"qq-[a-f0-9]{32}", event.session_id)
                    or not isinstance(event.occurred_at, datetime) or event.occurred_at.utcoffset() is None):
                raise ValueError("invalid_historical_qq_message")
        with self._lock:
            self._ensure_open()
            return self._method.import_dialogue(events)

    def dialogue_activity(self):
        with self._lock:
            return self._method.dialogue_activity()

    def recent_dialogue(self, limit=30, *, before_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("dialogue_limit_invalid")
        with self._lock:
            self._ensure_open()
            return self._method.recent_dialogue(limit, before_id=before_id)

    def _with_recent_dialogue(self, support, session_id, before_id=None):
        read = getattr(self._method, "recent_dialogue", None)
        if not callable(read) or not session_id:
            return support
        channel = ("web" if session_id.startswith("web:") else "qq" if session_id.startswith("qq-")
                   else "screen" if re.fullmatch("[0-9a-f]{24,32}", session_id) else None)
        rows = read(12, for_context=True, before_id=before_id)
        # 本端已有自己的聊天历史，仅补其他端和主动消息，避免重复计算同一轮。
        history = [{"端": row["channel"], "角色": row["role"], "时间": row["at"], "原话": row["text"][:360]}
                   for row in rows if row["channel"] != channel or row["proactive"]]
        if not history:
            return support
        block = "跨端近期对话（原话用于接续话题，助手曾说的话不能当作用户事实）：\n" + json.dumps(history, ensure_ascii=False)
        return replace(support, context="\n\n".join(filter(None, (support.context, block))))

    def outreach_context(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 16000:
            raise ValueError("outreach_query_invalid")
        with self._lock:
            self._ensure_open()
            if not self._use_enabled or self._closing or (self._model_service and self._model_service.pause_notice()):
                return ""
            support = self._method.recall(query)
            return self._with_recent_dialogue(support, "outreach").context if support.context.strip() else ""

    def prepare_user(
        self, text: str, *, defer_slow_observation: bool = False,
        event_id: str | None = None, session_id: str | None = None,
    ) -> PreparedMemoryTurn:
        started = perf_counter()
        event = MemoryEvent(event_id or str(uuid4()), "user", text, self._clock(), session_id)
        lock_started = perf_counter()
        with self._lock:
            lock_acquired = perf_counter()
            self._ensure_open()
            if self._model_service is not None:
                notice = self._model_service.pause_notice()
                if notice:
                    self._method.archive(event)
                    from longmemory.application.natural_memory_commands import NaturalMemoryCommandResult
                    return PreparedMemoryTurn(event,
                        ObservationResult(event.event_id, (), "source_only", "external_model_budget_paused"),
                        MemorySupport(str(uuid4()), "", (), "budget_paused"),
                        self._write_enabled, self._use_enabled,
                        MemoryPreparationTimings((lock_acquired - lock_started) * 1000, 0, 0, 0, 0, 0,
                                                 (perf_counter() - started) * 1000),
                        NaturalMemoryCommandResult("budget", "paused", notice))
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
                defer = getattr(self._method, "defer_observation", self._method.archive)
                observation = defer(event)
                self._deferred_events[event.event_id] = event
                observation = ObservationResult(
                    event.event_id, (), processing_status="source_only",
                    warning_code=observation.warning_code or "l1_extraction_deferred",
                )
            else:
                observation = (self._method.observe(event) if self._write_enabled
                               else self._method.archive(event))
            observe_finished = perf_counter()
            recall_started = perf_counter()
            support = (
                self._method.recall(text)
                if self._use_enabled
                else MemorySupport(str(uuid4()), "", (), "disabled_by_user", None)
            )
            if self._use_enabled and session_id and command is None:
                support = self._with_recent_dialogue(support, session_id, event.event_id)
            recall_finished = perf_counter()
            temporary_interaction = None
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
            if temporary_interaction is not None:
                combined = "\n\n".join(value for value in (
                    support.context, temporary_interaction.context,
                ) if value)
                retrieved = tuple(support.retrieved or ())
                strategy = "+".join(value for value in (
                    support.retrieval_strategy, "temporary_interaction_next_turn_v1",
                ) if value)
                support = MemorySupport(
                    support.call_id, combined, retrieved,
                    strategy, support.warning_code,
                )
            if command is not None:
                if isinstance(command, TemporaryInteractionCommandResult):
                    label = "[互动设置结果]"
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
        finished = perf_counter()
        timings = MemoryPreparationTimings(
            lock_wait_ms=round((lock_acquired - lock_started) * 1000, 3),
            command_ms=round((command_finished - command_started) * 1000, 3),
            observe_ms=round((observe_finished - observe_started) * 1000, 3),
            recall_ms=round((recall_finished - recall_started) * 1000, 3),
            scenario_ms=0, persona_ms=0,
            total_ms=round((finished - started) * 1000, 3),
        )
        return PreparedMemoryTurn(
            event, observation, support, write_enabled, use_enabled,
            timings, command, temporary_interaction,
        )

    def complete_deferred_observation(self, event_id: str, *, resume_pending=False) -> bool:
        """把已完成回答对应的 L1 派生交给受管队列；重复回执不重复提交。"""

        with self._lock:
            self._ensure_open()
            event = self._deferred_events.pop(event_id, None)
            if event is None and resume_pending and self._round_screen_store is not None:
                # 仅由这次明确完成回执恢复尚未调用引擎的 pending；重启不扫库重放。
                detail = self._method.source_detail(event_id)
                if detail["state"] == "pending":
                    event = MemoryEvent(event_id, detail["role"], detail["content"],
                        datetime.fromisoformat(detail["occurred_at"]), detail["session_id"])
            if event is None or self._closing:
                return False
            future = self._deferred_executor.submit(self._run_deferred_observation, event)
            self._deferred_futures.add(future)
            self._deferred_last_result = {"state": "running", "warning_code": None}
            future.add_done_callback(self._deferred_done)
            return True

    def prepare_round_screen(self, text, *, client_round_id, session_id, request_id=None, voice_round_id=None,
                             timing_callback=None):
        started, acquired, status = perf_counter(), None, 'failed'
        try:
            with self._lock:
                acquired = perf_counter()
                self._ensure_open()
                if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{24,32}", value) is None
                       for value in (client_round_id, session_id)):
                    raise ValueError("round_screen_metadata_invalid")
                if any(value is not None and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{24}", value) is None)
                       for value in (request_id, voice_round_id)):
                    raise ValueError("round_screen_request_identity_invalid")
                store = self._round_screen_store
                if store is None:
                    raise ValueError("round_screen_platform_unavailable")
                for expired in store.expire():
                    self._deferred_events.pop(expired, None)
                    self._proposal_formal.pop(expired, None)
                event_id = store.reserve(client_round_id=client_round_id, session_id=session_id,
                                         request_id=request_id, voice_round_id=voice_round_id)
                try:
                    prepared = self.prepare_user(text, event_id=event_id, session_id=session_id,
                                                 defer_slow_observation=True)
                    store.prepared(event_id, memory_receipt(prepared))
                except BaseException:
                    store.failed(event_id)
                    raise
                feedback = store.feedback(prepared.event, classify_explicit_round_screen_feedback(text))
                # 正式prepare已获写入授权；仅在内存留下短期比对摘要，不复制正文。
                # 候选不能自行伪造“已正式准备”的上下文或来源证明。
                if len(self._proposal_formal) >= 64:
                    self._proposal_formal.pop(next(iter(self._proposal_formal)))
                self._proposal_formal[event_id] = {
                    "client_round_id": client_round_id, "session_id": session_id,
                    "created": perf_counter(), "query": self._proposal_digest(text.strip()),
                    "context": self._proposal_digest(prepared.support.context),
                    "evidence": self._proposal_digest(memory_receipt(prepared)["evidence"]),
                    "eligible": (prepared.memory_command is None
                                 and feedback is None)}
                status = 'completed'
                return prepared, feedback
        finally:
            _emit_round_screen_timing(client_round_id, started, acquired, status, timing_callback)

    def complete_round_screen(self, *, turn_id, answer, receipt, client_round_id=None, request_id=None):
        with self._lock:
            self._ensure_open()
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 16000:
                raise ValueError("round_screen_answer_invalid")
            validate_receipt(receipt)
            assistant_id, created = self._round_screen_store.complete(event_id=turn_id,
                answer=answer, receipt=receipt, request_id=request_id, client_round_id=client_round_id)
            self._proposal_formal.pop(turn_id, None)
            # 来源与助手关联已持久提交，然后才排队；后台失败由来源账本保存。
            if self._round_screen_store.claim_dispatch(turn_id):
                self.complete_deferred_observation(turn_id, resume_pending=True)
            return PlatformTurnCompletion(assistant_id, created)

    def cancel_round_screen(self, turn_id, *, reason, client_round_id=None, request_id=None):
        with self._lock:
            self._ensure_open()
            result = self._round_screen_store.cancel(turn_id, reason=reason, client_round_id=client_round_id,
                                                    request_id=request_id)
            self._deferred_events.pop(turn_id, None)
            self._proposal_formal.pop(turn_id, None)
            return result

    def round_screen_status(self, turn_id):
        with self._lock:
            self._ensure_open()
            return self._round_screen_store.status(turn_id)

    def attach_model_service(self, service):
        """只供可信装配领取关闭责任，HTTP不提供替换模型服务的接口。"""
        with self._lock:
            self._ensure_open()
            if self._model_service is not None or self._closing:
                raise ValueError("model_service_already_owned_or_closing")
            self._model_service = service

    def external_model_settings(self, phase="answer"):
        with self._lock:
            self._ensure_open()
            if self._model_service is None:
                raise ValueError("owned_model_service_unavailable")
            return self._model_service.model_settings(phase)

    def voice_model_configuration(self):
        with self._lock:
            self._ensure_open()
            if self._model_service is None:
                raise ValueError("owned_model_service_unavailable")
            return self._model_service.voice_configuration()

    def _run_deferred_observation(self, event: MemoryEvent) -> ObservationResult:
        with self._lock:
            self._ensure_open()
            if not self._write_enabled:
                return ObservationResult(event.event_id, (), "source_only", "observation_paused")
            return self._method.complete_archived_observation(event)
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

    def external_text(self, role, text, *, event_id, session_id):
        """同一条平台消息在重投或工具多轮调用时只观察一次。"""
        with self._lock:
            self._ensure_open()
            try:
                previous = self._method.source_detail(event_id)
            except LookupError:
                previous = None
            if previous is not None:
                if (previous["role"], previous["content"], previous["session_id"]) != (role, text, session_id):
                    raise ValueError("external_message_conflict")
                if role != "user" or not self._use_enabled:
                    return ""
                return self._with_recent_dialogue(self._method.recall(text), session_id, event_id).context
            if role == "user":
                prepared = self.prepare_user(text, event_id=event_id, session_id=session_id)
                return prepared.support.context
            if role != "assistant":
                raise ValueError("external_role_invalid")
            self._method.archive(MemoryEvent(event_id, role, text, self._clock(), session_id))
            return ""

    def record_assistant(self, text: str, *, session_id=None) -> ObservationResult:
        event = MemoryEvent(str(uuid4()), "assistant", text, self._clock(), session_id)
        with self._lock:
            self._ensure_open()
            return self._method.observe(event)

    def administer(self, capability, operation, *args, **kwargs):
        with self._lock:
            self._ensure_open()
            assembly = self.backend_assembly
            admin = require_management(assembly.management if assembly else None, capability)
            allowed = {"listing": "list_items", "detail": "get_item",
                       "correction": "correct_item", "deletion": "delete_item"}
            if allowed.get(capability) != operation:
                raise ValueError("management_operation_invalid")
            if capability == "correction" and not self._write_enabled:
                raise ValueError("memory_write_paused")
            if capability == "correction" and kwargs["source"].role != "user":
                raise ValueError("memory_correction_source_must_be_user")
            if capability in {"correction", "deletion"}:
                self._proposal_revision += 1
            if capability == "correction":
                # 新引擎管理来源也先归档；管理失败不声称跨存储回滚。
                self._method.archive(kwargs["source"])
            return getattr(admin, operation)(*args, **kwargs)

    def source_status(self, event_id):
        with self._lock:
            self._ensure_open()
            status = getattr(self._method, "source_status", None)
            if status is None:
                raise ValueError("source_status_unsupported")
            return status(event_id)

    def administer_extension(self, namespace, operation, **arguments):
        """专属管理也经过统一串行和来源守卫，不能从HTTP任意调用方法。"""
        from longmemory.methods.contracts import UnsupportedCapabilityError
        allowed = {"workspace", "profile", "history", "operations", "correct", "delete", "mechanisms", "layer_page", "layer_detail",
                   "semantic_status", "semantic_task", "semantic_enqueue", "semantic_cancel"}
        layer_read = operation in {"layer_page", "layer_detail"}
        semantic_read = operation in {"semantic_status", "semantic_task"}
        # 仪表盘读取不能排在长模型/写入操作之后；未取得一致快照就明确busy。
        if not self._lock.acquire(blocking=operation != "mechanisms" and not layer_read and not semantic_read):
            if semantic_read:
                raise RuntimeError("hy_semantic_busy")
            if layer_read:
                raise MemoryReadBusyError("hy_layer_data_busy")
            raise RuntimeError("hy_mechanisms_busy")
        try:
            self._ensure_open()
            if (operation == "mechanisms" or layer_read or semantic_read) and self._closing:
                raise RuntimeError("hy_mechanisms_unavailable")
            assembly = self.backend_assembly
            admin = assembly.management if assembly else None
            if (namespace != "hy_memory" or operation not in allowed
                    or admin is None or getattr(admin, "extension_namespace", None) != namespace
                    or not callable(getattr(admin, "extension", None))):
                raise UnsupportedCapabilityError("memory_management_extension_unsupported")
            if operation.startswith("semantic_"):
                if self._closing:
                    raise RuntimeError("hy_semantic_unavailable")
                from .semantic_tasks import validate_semantic_request
                validate_semantic_request(operation, arguments)
                if operation == "semantic_enqueue" and not self._write_enabled:
                    raise ValueError("memory_write_paused")
            if operation in {"correct", "delete"}:
                if not self._write_enabled:
                    raise ValueError("memory_write_paused")
                source = arguments.get("source")
                request_id, item_id = arguments.get("request_id"), arguments.get("item_id")
                from uuid import UUID
                try:
                    valid_id = isinstance(request_id, str) and str(UUID(request_id)) == request_id
                except ValueError:
                    valid_id = False
                expected = arguments.get("content") if operation == "correct" else f"删除这条记忆：{item_id}"
                if (not valid_id or not isinstance(source, MemoryEvent) or source.role != "user"
                        or source.event_id != "hy-management:" + request_id or source.content != expected):
                    raise ValueError("memory_management_user_source_invalid")
                try:
                    previous = self._method.source_detail(source.event_id)
                except LookupError:
                    pass
                else:
                    if previous["role"] != "user" or previous["content"] != source.content:
                        raise ValueError("memory_management_source_conflict")
                    # HTTP重放会产生新接收时间；复用第一次真实来源，不能冲突覆盖。
                    source = MemoryEvent(source.event_id, "user", previous["content"],
                        datetime.fromisoformat(previous["occurred_at"]), previous["session_id"])
                # 管理可能在平台留下running/uncertain而SDK正文未变。先撤销旧候选，
                # 不能仅依赖原生内容digest发现来源叠加或不确定隔离的变化。
                self._proposal_revision += 1
                self._method.archive(source)
                arguments["source"] = source
            result = admin.extension(operation, **arguments)
            if operation == "semantic_status":
                # 不调用status()：仪表盘不应过期处理圆屏账本或执行懒初始化。
                if not isinstance(result, dict) or "runtime" in result:
                    raise RuntimeError("hy_semantic_envelope_conflict")
                result = {**result, "runtime": {"write_enabled": self._write_enabled,
                                                "use_enabled": self._use_enabled}}
            if operation == "mechanisms":
                # status()会过期处理圆屏账本；展示只观察当前内存门，不触碰持久状态。
                result = {**result, "runtime": {**result["runtime"],
                    "write_enabled": self._write_enabled, "use_enabled": self._use_enabled}}
            return result
        finally:
            self._lock.release()

    def source_detail(self, event_id):
        with self._lock:
            self._ensure_open()
            detail = getattr(self._method, "source_detail", None)
            if detail is None:
                from longmemory.methods.contracts import UnsupportedCapabilityError
                raise UnsupportedCapabilityError("source_detail_unsupported")
            return detail(event_id)

    def retry_source(self, event_id, *, expected_attempt_id):
        with self._lock:
            self._ensure_open()
            if not self._write_enabled:
                raise ValueError("memory_write_paused")
            retry = getattr(self._method, "retry_observation", None)
            if retry is None:
                raise ValueError("source_retry_unsupported")
            return retry(event_id, expected_attempt_id=expected_attempt_id)

    def identity(self) -> dict:
        """全站导航身份：只读内存，不初始化方法、不刷新账本或等模型锁。"""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("memory_identity_busy")
        try:
            self._ensure_open()
            if self._closing:
                raise RuntimeError("memory_identity_unavailable")
            return {"schema_version": 1, "configured": True,
                    "method": self._method.name,
                    "representation": "method_defined",
                    "legacy_sqlite": False, "state": "available"}
        finally:
            self._lock.release()

    def status(self) -> dict:
        with self._lock:
            self._ensure_open()
            if self._round_screen_store is not None:
                for expired in self._round_screen_store.expire():
                    self._deferred_events.pop(expired, None)
            self._method.wait_until_ready()
            return {
                "ready": True,
                "method": self._method.name,
                "implementation_version": self._method.implementation_version,
                "state_identity": self._state_identity,
                "external_models": self._model_service.status() if self._model_service is not None else None,
                "retrieval": getattr(self._method, "retrieval_name", "unknown"),
                "database": str(self.database),
                "state_resources": ([{"name": item.name, "kind": item.kind,
                                      "path": str(item.path)}
                                     for item in self.backend_assembly.resources]
                                    if self.backend_assembly else []),
                "method_capabilities": asdict(self._method.capabilities),
                "management_capabilities": (asdict(self.backend_assembly.management.capabilities)
                    if self.backend_assembly and self.backend_assembly.management else {}),
                "legacy_sqlite": False,
                "proactive": {"available": False, "state": "paused_backend_unsupported"},
                "write_enabled": self._write_enabled,
                "use_enabled": self._use_enabled,
                "scenario_use_enabled": False,
                "scenario_available": False,
                "persona_use_enabled": False,
                "persona_available": False,
                "temporal_history_available": False,
                "temporary_interaction_available": False,
                "next_interaction_armed": self._next_interaction is not None,
                "settings_persistent": False,
                "deferred_observation": {
                    "supported": self._method.capabilities.deferred_observation,
                    "awaiting_completion": len(self._deferred_events),
                    "running_or_queued": len(self._deferred_futures),
                    "last_result": dict(self._deferred_last_result),
                },
                "consolidation_scheduler": {"enabled": False, "available": False},
                "l2_sufficiency_shadow": {"enabled": False, "state": "disabled"},
                "l1_sufficiency_shadow": {"enabled": False, "state": "disabled"},
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
            if scenario_use_enabled:
                raise ValueError("scenario_memory_unavailable")
            if persona_use_enabled:
                raise ValueError("persona_memory_unavailable")
            proposal_changed = write_enabled != self._write_enabled or use_enabled != self._use_enabled
            if write_enabled != self._confirmed_background_write_enabled:
                self._sync_background_writes(write_enabled)
            self._write_enabled = write_enabled
            self._use_enabled = use_enabled
            if proposal_changed:
                self._proposal_revision += 1
            return self.status()

    def _sync_background_writes(self, write_enabled):
        gate = getattr(self._method, "configure_background_writes", None)
        if callable(gate):
            try:
                gate(write_enabled=write_enabled)
            except Exception:
                # 未能证明后台屏障已更新时，前台至少保持暂停；不伪报任务回滚。
                self._confirmed_background_write_enabled = None
                self._write_enabled = False
                self._proposal_revision += 1
                raise RuntimeError("memory_background_write_gate_failed") from None
        self._confirmed_background_write_enabled = write_enabled

    def candidate_memory_snapshot(self, query, *, limit=5):
        """宿主候选专用读取；绝不调用prepare/recall/reserve/归档或派生接口。

        向量沿宿主已有CPU编码器和网关embedding锁产生，不携带供应商凭据。
        引擎短期令牌仍由Hy真实只读路径签发；这里额外绑定Runtime实例和设置。
        """
        from longmemory.methods.contracts import UnsupportedCapabilityError
        if not isinstance(query, str) or not query.strip() or len(query) > 16000:
            raise ValueError("candidate_query_invalid")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("candidate_limit_invalid")
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("candidate_memory_busy")
        try:
            self._ensure_open()
            snapshot = getattr(self._method, "candidate_snapshot", None)
            gateway = getattr(self._model_service, "gateway", None)
            if self._closing or not self._use_enabled:
                raise RuntimeError("candidate_memory_unavailable")
            if not callable(snapshot) or gateway is None:
                raise UnsupportedCapabilityError("candidate_memory_unsupported")
            revision = self._candidate_runtime_revision()
            encoder = gateway.encoder
        finally:
            self._lock.release()
        # CPU编码可能等待共享向量器；不能带着Runtime锁阻挡正式prepare/管理。
        # 仍复用原网关编码锁，不增加并发工位；迟到编码只可被重新验证或丢弃。
        encoded = gateway.embed({"model": encoder.identity, "input": [query]}, "query")
        vector = encoded["data"][0]["embedding"]
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("candidate_memory_busy")
        try:
            self._ensure_open()
            if (self._closing or not self._use_enabled or self._candidate_runtime_revision() != revision
                    or getattr(self._model_service, "gateway", None) is not gateway or gateway.encoder is not encoder):
                raise RuntimeError("candidate_memory_stale")
            result = snapshot(query_embedding=vector, limit=limit)
            if not isinstance(result, dict):
                raise RuntimeError("candidate_memory_response_invalid")
            return {"engine": result, "runtime_revision": self._candidate_runtime_revision()}
        finally:
            self._lock.release()

    def _candidate_runtime_revision(self):
        return self._proposal_instance + ":" + str(self._proposal_revision)

    def candidate_model_binding(self):
        """只供宿主装配取得现有已核验网关；不向小智/HTTP返回供应商凭据。"""
        with self._lock:
            self._ensure_open()
            gateway = getattr(self._model_service, "gateway", None)
            if self._closing or gateway is None:
                raise RuntimeError("candidate_model_unavailable")
            return {**gateway.candidate_response_binding(), "policy_revision": self.candidate_policy_revision()}

    def candidate_policy_revision(self):
        """模型/政策/Runtime设置的内部版本；角色、日期和历史另由实际消息绑定。"""
        with self._lock:
            self._ensure_open()
            gateway = getattr(self._model_service, "gateway", None)
            if self._closing or gateway is None:
                raise RuntimeError("candidate_model_unavailable")
            # 完整设置只进哈希；凭据和端点绝不作为候选状态或诊断字段返回。
            return self._proposal_digest({"runtime": self._candidate_runtime_revision(),
                "model": asdict(gateway.settings), "policy": gateway.budget.identity,
                "embedding": gateway.encoder.identity,
                "method": self._method.implementation_version})

    @staticmethod
    def _proposal_digest(value):
        return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def claim_candidate_memory(self, receipt, *, query, formal_turn_id, client_round_id,
                               session_id, claim):
        """同一前台临界区内比对正式正文/来源、fresh令牌并同步一次性领取。

        claim只能是进程内同步领取函数，不能执行网络、TTS或任何正式入库。
        返回客户端后仍由语音侧在原取消门内同步检查epoch再入队。
        """
        with self._lock:
            self._ensure_open()
            record = self._proposal_formal.get(formal_turn_id)
            if (self._closing or record is None or not record["eligible"]
                    or perf_counter() - record["created"] > 30
                    or record["client_round_id"] != client_round_id or record["session_id"] != session_id
                    or record["query"] != self._proposal_digest(query.strip())):
                return None
            engine = receipt["engine"]
            if engine.get("read_status") != "readable":
                return None
            rows = engine["items"]
            context = "\n".join(row["content"] for row in rows)
            evidence = [{"item_id": row["memory_id"], "rank": rank,
                         "content_sha256": sha256(row["content"].encode()).hexdigest(),
                         "source_event_ids": row["source_event_ids"]} for rank, row in enumerate(rows, 1)]
            if (record["context"] != self._proposal_digest(context)
                    or record["evidence"] != self._proposal_digest(evidence)):
                return None
            valid = self.validate_candidate_memory(snapshot_token=engine["snapshot_token"],
                memory_digest=engine["memory_digest"], runtime_revision=receipt["runtime_revision"])
            if (not isinstance(valid, dict) or valid.get("protocol") != 1 or valid.get("valid") is not True
                    or valid.get("memory_digest") != engine["memory_digest"]):
                return None
            # 从fresh校验到claim没有await；正式源归档/工具/音频仍不在候选内执行。
            text = claim()
            if text is not None:
                if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                    raise ValueError("candidate_claim_invalid")
                self._proposal_formal.pop(formal_turn_id, None)
            return text

    def validate_candidate_memory(self, *, snapshot_token, memory_digest, runtime_revision):
        """正式采用前重验宿主设置与引擎令牌；结果只供宿主候选服务使用。"""
        from longmemory.methods.contracts import UnsupportedCapabilityError
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("candidate_memory_busy")
        try:
            self._ensure_open()
            if self._closing or not self._use_enabled or runtime_revision != self._candidate_runtime_revision():
                return False
            validate = getattr(self._method, "candidate_validate", None)
            if not callable(validate):
                raise UnsupportedCapabilityError("candidate_memory_unsupported")
            return validate(snapshot_token=snapshot_token, memory_digest=memory_digest)
        finally:
            self._lock.release()

    def close(self) -> None:
        # 不能在持锁状态 shutdown：正在完成模型调用的工作线程随后还需
        # 取得同一把锁写入 SQLite，否则会形成停机死锁。
        with self._lock:
            if self._closed or self._closing:
                return
            self._closing = True
            self._deferred_events.clear()
            self._proposal_formal.clear()
        self._deferred_executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            if not self._closed:
                try:
                    self._method.close()
                finally:
                    if self._memory_command_handler is not None:
                        self._memory_command_handler.close()
                    self._closed = True
                    if self._model_service is not None:
                        self._model_service.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("记忆运行时已经关闭。")
