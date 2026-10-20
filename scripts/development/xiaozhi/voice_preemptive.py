"""受控提前生成：冻结上下文进入，确认后的一次性凭据退出。

无 Memory、prepare/search、工具、归档、字幕或播放接口。所有方法由同一
asyncio 事件循环调用；来自音频线程的事件须先投递到该循环。默认关闭。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import time
from typing import AsyncContextManager, AsyncIterator, Protocol


def _valid_messages(messages):
    return (type(messages) is tuple and 1 <= len(messages) <= 128
            and all(type(row) is tuple and len(row) == 2
                    and isinstance(row[0], str) and row[0] in {"system", "user", "assistant"}
                    and isinstance(row[1], str) for row in messages)
            and messages[0][0] == "system"
            and not any(role == "system" for role, _ in messages[1:])
            and sum(len(text) for _, text in messages) <= 32000)


@dataclass(frozen=True)
class TurnStamp:
    turn_id: int
    transcript_revision: int
    cancel_epoch: int

    def __post_init__(self):
        if any(type(x) is not int or x < 0 for x in (
                self.turn_id, self.transcript_revision, self.cancel_epoch)):
            raise ValueError("preemptive_turn_invalid")


@dataclass(frozen=True)
class SnapshotVersion:
    memory_revision: str
    context_revision: str
    tools_revision: str
    policy_revision: str

    def __post_init__(self):
        if any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in (
                self.memory_revision, self.context_revision,
                self.tools_revision, self.policy_revision)):
            raise ValueError("preemptive_version_invalid")


@dataclass(frozen=True)
class ContextSnapshot:
    """仅冻结已经取得的文本；不调用检索器，也不宣称普通 search 是只读。

    version 必须来自经过审查的 proposal-only 快照提供者。digest 仅在内存中
    对比，不进入观测输出。历史工具消息不在本接口支持范围，正式链路处理。
    """

    version: SnapshotVersion
    messages: tuple[tuple[str, str], ...] = field(repr=False)
    digest: str = field(init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.version, SnapshotVersion):
            raise ValueError("preemptive_version_invalid")
        if not _valid_messages(self.messages):
            raise ValueError("preemptive_snapshot_invalid")
        data = json.dumps(self.messages, ensure_ascii=False, separators=(",", ":"))
        object.__setattr__(self, "digest", hashlib.sha256(data.encode()).hexdigest())


@dataclass(frozen=True)
class Limits:
    enabled: bool = False
    timeout_seconds: float = 2.0
    ready_ttl_seconds: float = 3.0
    max_input_chars: int = 16000
    max_output_chars: int = 2048
    max_output_tokens: int = 256

    def __post_init__(self):
        if (type(self.enabled) is not bool
                or any(type(x) not in {int, float} or not math.isfinite(x) or x <= 0
                       for x in (self.timeout_seconds, self.ready_ttl_seconds))
                or self.timeout_seconds > 10 or self.ready_ttl_seconds > 10
                or any(type(x) is not int or x <= 0 for x in (
                    self.max_input_chars, self.max_output_chars, self.max_output_tokens))
                or self.max_input_chars > 32000 or self.max_output_chars > 8192
                or self.max_output_tokens > 1024):
            raise ValueError("preemptive_limits_invalid")


@dataclass
class CloseConfirmation:
    """传输明确要求关闭回执时，异常退出不能伪装成上游已关闭。"""

    required: bool = False
    confirmed: bool = False


@dataclass(frozen=True)
class RequestScope:
    """语音RPC携带的临时归属；不是鉴权凭据，也不是个人/设备标识。"""

    owner_id: str = field(repr=False)
    connection_id: str = field(repr=False)
    turn: TurnStamp
    audio_revision: int

    def __post_init__(self):
        if (any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None
                for value in (self.owner_id, self.connection_id))
                or type(self.turn) is not TurnStamp
                or type(self.audio_revision) is not int or self.audio_revision < 0):
            raise ValueError("preemptive_request_scope_invalid")


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[tuple[str, str], ...] = field(repr=False)
    max_output_tokens: int
    close_confirmation: CloseConfirmation = field(default_factory=CloseConfirmation,
                                                   repr=False, compare=False)
    scope: RequestScope | None = field(default=None, repr=False)

    def __post_init__(self):
        if (not _valid_messages(self.messages) or self.messages[-1][0] != "user"
                or type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 1024):
            raise ValueError("preemptive_request_invalid")
        if self.scope is not None and type(self.scope) is not RequestScope:
            raise ValueError("preemptive_request_scope_invalid")
        if type(self.close_confirmation) is not CloseConfirmation:
            raise ValueError("preemptive_close_confirmation_invalid")


class TextStream(Protocol):
    usage: dict | None

    def __aiter__(self) -> AsyncIterator[str]: ...


class PreparationModel(Protocol):
    # 由装配层核对真实网关免费策略与重试策略；不能用本标记替代费用账本。
    billing_class: str
    automatic_retries: bool

    def open(self, request: ModelRequest) -> AsyncContextManager[TextStream]: ...


class RequestBudget:
    """跨连接共用的进程内计算上限；不结算/释放网关的费用或 unknown 预留。

    请求次数/输入/输出最坏预留是本实例生命周期累计值，取消不退还。
    active 仅在协程及流退出后释放，取消事件本身不释放。
    """

    def __init__(self, *, max_active=1, max_requests=20,
                 max_input_chars=160000, max_reserved_output_tokens=5120):
        if any(type(x) is not int or x <= 0 for x in (
                max_active, max_requests, max_input_chars, max_reserved_output_tokens)):
            raise ValueError("preemptive_budget_invalid")
        self.max_active = max_active
        self.max_requests = max_requests
        self.max_input_chars = max_input_chars
        self.max_reserved_output_tokens = max_reserved_output_tokens
        self.active = self.requests = self.input_chars = self.output_tokens = 0
        self._loop = None

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("preemptive_event_loop_mismatch")
        self._loop = loop

    def reserve(self, size, tokens):
        self._check_loop()
        if self.active >= self.max_active:
            return "busy"
        if (self.requests >= self.max_requests
                or self.input_chars + size > self.max_input_chars
                or self.output_tokens + tokens > self.max_reserved_output_tokens):
            return "budget"
        self.active += 1
        self.requests += 1
        self.input_chars += size
        self.output_tokens += tokens
        return None

    def release(self):
        self._check_loop()
        self.active -= 1

    def snapshot(self):
        return {"active": self.active, "reserved_requests": self.requests,
                "reserved_input_chars": self.input_chars,
                "reserved_output_tokens": self.output_tokens}


@dataclass(eq=False)
class _Candidate:
    turn: TurnStamp
    context: ContextSnapshot
    transcript: str = field(repr=False)
    request: ModelRequest = field(repr=False)
    started_at: float
    model_user_message: str = field(repr=False)
    separate_payload: bool
    valid: bool = True
    task: asyncio.Task | None = None
    timer: asyncio.TimerHandle | None = None
    text: str = field(default="", repr=False)
    usage: dict | None = None
    ready_at: float | None = None
    confirmed: bool = False
    claimed: bool = False
    started: bool = False
    closing: bool = False
    invalidated: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ConfirmedCandidate:
    """不直接暴露正文；派发前再次核对代次/快照，一次性领取。

    claim 与正式链路取消门的检查/入队之间不得插入 await；之后的播放、
    字幕和正式提交仍由原有话轮生命周期约束，不能把本凭据当播放授权。
    """

    def __init__(self, owner, candidate):
        self._owner, self._candidate = owner, candidate

    def claim(self, *, turn: TurnStamp, context: ContextSnapshot, model_user_message=None):
        return self._owner._claim(self._candidate, turn, context, model_user_message)


_REASONS = frozenset({"continued", "cancelled", "context_changed", "revised",
                      "new_turn", "closed", "timeout", "expired", "mismatch",
                      "failed", "caller_cancelled"})


class VoicePreemptive:
    """每连接一实例，每真实话轮最多一次；重启不恢复任何候选。"""

    def __init__(self, model: PreparationModel, budget: RequestBudget, *, limits=None):
        self.model, self.budget = model, budget
        self.limits = limits or Limits()
        self._loop = None
        self._turn_id = self._epoch = -1
        self._attempted = self._closed = False
        self._candidate = None
        self._tasks = set()
        self._unclosed = set()
        self._last_status = "idle"
        self._counts = dict.fromkeys((
            "admitted", "started", "ready", "confirmed", "hits", "misses",
            "discarded", "timeouts", "failed", "unknown_usage", "skipped_busy",
            "skipped_budget", "skipped_disabled", "skipped_policy", "skipped_size",
            "discarded_reserved_output_tokens", "observed_output_chars",
            "observed_input_tokens", "observed_output_tokens", "discarded_elapsed_ms",
            "cleanup_unconfirmed",
        ), 0)

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("preemptive_event_loop_mismatch")
        self._loop = loop
        self._reap_closed()

    def _reap_closed(self):
        for candidate in tuple(self._unclosed):
            if candidate.request.close_confirmation.confirmed:
                self.budget.release()
                self._unclosed.remove(candidate)

    def _invalidate(self, reason):
        if reason not in _REASONS:
            raise ValueError("preemptive_reason_invalid")
        candidate, self._candidate = self._candidate, None
        self._last_status = reason
        if candidate is None or not candidate.valid:
            return
        candidate.valid, candidate.text = False, ""
        candidate.invalidated.set()
        if candidate.timer:
            candidate.timer.cancel()
        if not candidate.claimed:
            self._counts["discarded"] += 1
            self._counts["discarded_reserved_output_tokens"] += candidate.request.max_output_tokens
            self._counts["discarded_elapsed_ms"] += round((time.monotonic() - candidate.started_at) * 1000)
        if (candidate.task is not None and not candidate.task.done()
                and not candidate.closing and candidate.task is not asyncio.current_task()):
            candidate.task.cancel()

    def _advance(self, turn):
        self._check_loop()
        if type(turn) is not TurnStamp:
            raise ValueError("preemptive_turn_invalid")
        if self._closed or turn.turn_id < self._turn_id or turn.cancel_epoch < self._epoch:
            return False
        if turn.turn_id > self._turn_id:
            self._invalidate("new_turn")
            self._turn_id, self._attempted = turn.turn_id, False
        if turn.cancel_epoch > self._epoch:
            self._invalidate("cancelled")
            self._epoch = turn.cancel_epoch
        return True

    def provisional(self, *, turn: TurnStamp, transcript: str, context: ContextSnapshot,
                    scope: RequestScope | None = None, model_user_message=None):
        """只调度，不阻塞音频循环。重复/修订不为同轮重新发请求。"""
        if type(context) is not ContextSnapshot:
            raise ValueError("preemptive_frozen_snapshot_required")
        if scope is not None and (type(scope) is not RequestScope or scope.turn != turn):
            raise ValueError("preemptive_request_scope_invalid")
        if model_user_message is not None and (not isinstance(model_user_message, str)
                                               or not model_user_message.strip()):
            raise ValueError("preemptive_model_user_invalid")
        if not self._advance(turn):
            return False
        candidate = self._candidate
        if candidate is not None and not self._matches(candidate, turn, transcript, context, model_user_message):
            self._invalidate("revised")
        if self._attempted:
            return False
        if not self.limits.enabled:
            self._counts["skipped_disabled"] += 1
            return False
        self._attempted = True
        if (getattr(self.model, "billing_class", None) != "campus_free_verified"
                or getattr(self.model, "automatic_retries", None) is not False):
            self._counts["skipped_policy"] += 1
            return False
        size = sum(len(text) for _, text in context.messages)
        actual_user = transcript if model_user_message is None else model_user_message
        if (not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 16000
                or not isinstance(actual_user, str) or len(actual_user) > 16000
                or size + len(actual_user) > self.limits.max_input_chars
                or len(context.messages) >= 128):
            self._counts["skipped_size"] += 1
            return False
        status = self.budget.reserve(size + len(actual_user), self.limits.max_output_tokens)
        if status:
            self._counts["skipped_" + status] += 1
            self._last_status = status
            return False
        request = ModelRequest(context.messages + (("user", actual_user),), self.limits.max_output_tokens,
                               scope=scope)
        candidate = _Candidate(turn, context, transcript, request, time.monotonic(),
                               actual_user, model_user_message is not None)
        self._candidate = candidate
        self._counts["admitted"] += 1
        self._last_status = "preparing"
        task = candidate.task = asyncio.create_task(self._run(candidate))
        self._tasks.add(task)
        task.add_done_callback(lambda task: self._finished(candidate, task))
        candidate.timer = self._loop.call_later(self.limits.timeout_seconds, self._timeout, candidate)
        return True

    @staticmethod
    def _matches(candidate, turn, transcript, context, model_user_message=None):
        return (candidate.valid and candidate.turn == turn and candidate.transcript == transcript
                and candidate.separate_payload == (model_user_message is not None)
                and candidate.model_user_message == (transcript if model_user_message is None else model_user_message)
                and candidate.context.version == context.version
                and candidate.context.digest == context.digest)

    def _current(self, candidate):
        return (not self._closed and self._candidate is candidate and candidate.valid
                and candidate.turn.turn_id == self._turn_id
                and candidate.turn.cancel_epoch == self._epoch)

    def _timeout(self, candidate):
        if self._current(candidate) and candidate.ready_at is None:
            self._counts["timeouts"] += 1
            self._invalidate("timeout")

    async def _run(self, candidate):
        try:
            if not self._current(candidate):
                return
            candidate.started = True
            self._counts["started"] += 1
            read_complete = False
            # 只在退出 async with（包括响应关闭）之后才能 ready 或释放 active。
            async with self.model.open(candidate.request) as stream:
                try:
                    parts, size = [], 0
                    async for text in stream:
                        if not self._current(candidate):
                            return
                        if not isinstance(text, str):
                            raise ValueError("preemptive_output_invalid")
                        size += len(text)
                        self._counts["observed_output_chars"] += len(text)
                        if size > self.limits.max_output_chars:
                            raise ValueError("preemptive_output_too_large")
                        parts.append(text)
                    candidate.usage = _usage(stream.usage)
                    read_complete = True
                finally:
                    # 撤销只唤醒最终端点；不能把已开始的异步关闭本身取消掉。
                    # 同任务退出也保留上下文管理器的 ContextVar 归属。
                    candidate.closing = True
            if not self._current(candidate):
                return
            if not read_complete:
                raise ValueError("preemptive_read_incomplete")
            text = "".join(parts)
            if not text.strip():
                raise ValueError("preemptive_empty_answer")
            candidate.text, candidate.ready_at = text, time.monotonic()
            candidate.timer.cancel()
            candidate.timer = self._loop.call_later(
                self.limits.ready_ttl_seconds, self._expire, candidate)
            self._counts["ready"] += 1
            self._last_status = "ready"
        except asyncio.CancelledError:
            # 取消方同步撤销有效性；即使传输吞掉取消，_current 也不再允许结果。
            raise
        except Exception:
            self._counts["failed"] += 1
            if self._current(candidate):
                self._invalidate("failed")

    def _finished(self, candidate, task):
        self._tasks.discard(task)
        confirmation = candidate.request.close_confirmation
        if confirmation.required and not confirmation.confirmed:
            self._unclosed.add(candidate)
            self._counts["cleanup_unconfirmed"] += 1
        else:
            self.budget.release()
        if candidate.started and candidate.usage is None:
            self._counts["unknown_usage"] += 1
        elif candidate.usage is not None:
            self._counts["observed_input_tokens"] += candidate.usage["prompt_tokens"]
            self._counts["observed_output_tokens"] += candidate.usage["completion_tokens"]
        # 读取异常避免任务日志带出供应商异常；不保留异常正文。
        if not task.cancelled():
            task.exception()

    def _expire(self, candidate):
        if self._current(candidate):
            self._invalidate("expired")

    async def confirmed(self, *, turn: TurnStamp, transcript: str, context: ContextSnapshot, model_user_message=None):
        """最终端点才能调用；等待已有请求，不发起第二次请求或正式 prepare。"""
        if type(context) is not ContextSnapshot:
            raise ValueError("preemptive_frozen_snapshot_required")
        if not self._advance(turn):
            return None
        self._attempted = True  # 确认后迟到的 provisional 不能反向启动请求。
        candidate = self._candidate
        if candidate is None or not self._matches(candidate, turn, transcript, context, model_user_message):
            self._counts["misses"] += 1
            self._invalidate("mismatch")
            return None
        invalidated = asyncio.create_task(candidate.invalidated.wait())
        try:
            # 即使网络清理吞掉取消，也不能让最终端点一直等待旧候选。
            await asyncio.wait({candidate.task, invalidated}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            if self._current(candidate):
                self._invalidate("caller_cancelled")
            raise
        finally:
            invalidated.cancel()
            await asyncio.gather(invalidated, return_exceptions=True)
        if not self._current(candidate) or candidate.ready_at is None or candidate.claimed:
            self._counts["misses"] += 1
            return None
        if not candidate.confirmed:
            self._counts["confirmed"] += 1
            candidate.confirmed = True
        return ConfirmedCandidate(self, candidate)

    def _claim(self, candidate, turn, context, model_user_message=None):
        self._check_loop()
        if type(context) is not ContextSnapshot or type(turn) is not TurnStamp:
            return None
        if not self._current(candidate) or not candidate.confirmed or candidate.claimed:
            return None
        if not self._matches(candidate, turn, candidate.transcript, context, model_user_message):
            self._invalidate("mismatch")
            return None
        if time.monotonic() - candidate.ready_at >= self.limits.ready_ttl_seconds:
            self._invalidate("expired")
            return None
        candidate.claimed = True
        text, candidate.text = candidate.text, ""
        candidate.valid = False
        candidate.invalidated.set()
        self._candidate = None
        candidate.timer.cancel()
        self._counts["hits"] += 1
        self._last_status = "claimed"
        return text

    def continued(self, *, turn_id: int, cancel_epoch: int):
        self.cancel(turn_id=turn_id, cancel_epoch=cancel_epoch, reason="continued")

    def begin_turn(self, *, turn_id: int, cancel_epoch: int):
        """新一轮刚开始发声即可撤销旧结果，不必等待首个ASR/记忆快照。"""
        return self._advance(TurnStamp(turn_id, 0, cancel_epoch))

    def revised(self, *, turn: TurnStamp):
        """只转发修订代次；无需为取消调用检索或构造新快照。"""
        if self._advance(turn) and self._candidate is not None and self._candidate.turn != turn:
            self._invalidate("revised")

    def cancel(self, *, turn_id: int, cancel_epoch: int, reason="cancelled"):
        if reason not in {"continued", "cancelled"}:
            raise ValueError("preemptive_reason_invalid")
        turn = TurnStamp(turn_id, 0, cancel_epoch)
        if self._advance(turn):
            self._attempted = True
            self._invalidate(reason)

    def context_changed(self, version: SnapshotVersion | None = None):
        self._check_loop()
        if version is not None and type(version) is not SnapshotVersion:
            raise ValueError("preemptive_version_invalid")
        if self._candidate is not None and (version is None or self._candidate.context.version != version):
            self._invalidate("context_changed")

    def close(self):
        self._check_loop()
        self._closed = True
        self._invalidate("closed")

    async def aclose(self, *, timeout_seconds=1.0):
        """有界等待响应实际关闭；False 表示仍在清理，active 仍保留。"""
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("preemptive_close_timeout_invalid")
        self.close()
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=timeout_seconds)
            self._reap_closed()
            return not pending and not self._unclosed
        return not self._unclosed

    def snapshot(self):
        """只输出有限状态、成本计数与命中率，不输出正文/ID/摘要/异常。"""
        admitted = self._counts["admitted"]
        return {"version": 1, "enabled": self.limits.enabled, "closed": self._closed,
                "state": self._last_status, **self._counts,
                "unconfirmed_closes": len(self._unclosed),
                "hit_rate": self._counts["hits"] / admitted if admitted else None,
                "budget": self.budget.snapshot()}


def _usage(value):
    if (not isinstance(value, dict) or any(type(value.get(key)) is not int
            or value[key] < 0 for key in ("prompt_tokens", "completion_tokens"))):
        return None
    return {key: value[key] for key in ("prompt_tokens", "completion_tokens")}
