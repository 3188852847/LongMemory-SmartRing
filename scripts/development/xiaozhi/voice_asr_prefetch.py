"""让本地 SenseVoice 的一次预识别与停嘴等待重叠。

这不是提前开始聊天：300ms 静音时只在内存中算一个候选，仍由上游正式 VAD
端点决定何时提交。继续说话、重新监听或断开连接都会废弃候选。本模块不调用
Memory、LLM、上报或文件接口，也不把候选正文、音频或其摘要放入观测结果。
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
import hashlib
import threading
import time


_FORMAL = ContextVar("longmemory_asr_prefetch_formal", default=None)
_MODEL_WAIT = ContextVar("longmemory_asr_prefetch_model_wait", default=None)
_STATE = "_longmemory_asr_prefetch_state"
_GATE = "_longmemory_asr_prefetch_gate"


class _Ticket:
    def __init__(self, pcm, generation, voice_stamp, language):
        self.pcm = pcm
        self.size = len(pcm)
        # 只比较旧快照前缀，允许正式输入追加静音尾；发声代次仍须单独一致。
        self.prefix_digest = hashlib.sha256(pcm).digest()
        self.generation = generation
        self.voice_stamp = voice_stamp
        self.language = language
        self.valid = threading.Event()
        self.valid.set()
        self.task = None
        self.started = None
        self.finished = None
        self.result = None
        self.status = "scheduled"


class _State:
    def __init__(self):
        self.generation = 0
        self.voice_stamp = None
        self.attempted = False
        self.ticket = None
        self.closed = False
        self.counts = {key: 0 for key in (
            "started", "reused", "invalidated", "skipped_busy", "failed", "fallback",
        )}
        self.latest_status = "idle"
        self.latest_prefetch_ms = None
        self.latest_formal_wait_ms = None
        self.latest_model_queue_ms = None
        self.latest_overlap_ms = None

    def invalidate(self, reason, *, reset=False):
        ticket = self.ticket
        if ticket is not None and ticket.valid.is_set():
            ticket.valid.clear()
            ticket.result = None
            self.counts["invalidated"] += 1
        self.ticket = None
        if ticket is not None or reason == "closed":
            self.latest_status = reason
        if reset:
            self.generation += 1
            self.attempted = False
            self.voice_stamp = None

    def snapshot(self):
        return {"version": 1, "enabled": True, **self.counts,
                "latest_status": self.latest_status,
                "latest_prefetch_ms": self.latest_prefetch_ms,
                "latest_formal_wait_ms": self.latest_formal_wait_ms,
                "latest_model_queue_ms": self.latest_model_queue_ms,
                "latest_overlap_ms": self.latest_overlap_ms}


def voice_asr_prefetch_snapshot(connection):
    """只输出计数与毫秒耗时，不暴露会话身份、候选正文或音频摘要。"""
    state = getattr(connection, _STATE, None)
    if state is not None:
        return state.snapshot()
    if getattr(connection, "_longmemory_asr_prefetch_enabled", False) is True:
        return _State().snapshot()
    return {"version": 1, "enabled": False}


class _ModelGate:
    """锁住实际同步推理，而不是可被取消的 asyncio 等待。

FunASR 会就地修改模型 kwargs，不能并发 generate。正式识别和预识别共用
    此锁；取消协程无法停止正在执行的模型线程，所以不提前释放锁，也不把
一个已失效任务伪装成“已停止”。繁忙时预识别直接跳过，正式识别仍需排队。
"""

    def __init__(self, generate):
        self.original = generate
        self.lock = threading.Lock()

    def generate(self, *args, **kwargs):
        started = time.perf_counter()
        with self.lock:
            metrics = _MODEL_WAIT.get()
            if metrics is not None:
                metrics["wait_ms"] = round((time.perf_counter() - started) * 1000)
            return self.original(*args, **kwargs)

    def prefetch(self, ticket):
        if not self.lock.acquire(blocking=False):
            ticket.pcm = b""
            return "busy", None
        try:
            if not ticket.valid.is_set():
                return "invalidated", None
            pcm, ticket.pcm = ticket.pcm, b""
            ticket.started = time.perf_counter()
            result = self.original(
                input=pcm, cache={}, language=ticket.language,
                use_itn=True, batch_size_s=60,
            )
            ticket.finished = time.perf_counter()
            return "ready", result
        finally:
            ticket.pcm = b""
            self.lock.release()


def _gate_for(provider):
    model = provider.model
    gate = getattr(model, _GATE, None)
    if gate is None:
        gate = _ModelGate(model.generate)
        # 同一个共享 AutoModel 的所有 generate 调用都通过同一线程锁。
        model.generate = gate.generate
        setattr(model, _GATE, gate)
    return gate


def _eligible(provider, connection):
    model_dir = str(getattr(provider, "model_dir", "")).replace("\\", "/").rstrip("/")
    model_kwargs = getattr(getattr(provider, "model", None), "kwargs", {})
    return (
        model_dir.rsplit("/", 1)[-1] == "SenseVoiceSmall"
        and getattr(getattr(provider, "interface_type", None), "value", None) == "LOCAL"
        and getattr(connection, "client_listen_mode", None) in {"auto", "realtime"}
        and not getattr(connection, "voiceprint_provider", None)
        and getattr(provider, "delete_audio_file", None) is True
        and isinstance(model_kwargs, dict) and model_kwargs.get("output_dir") is None
        and not connection.stop_event.is_set()
    )


def _stamp(connection):
    value = getattr(connection, "vad_last_voice_time", None)
    return value if type(value) in {float, int} and value > 0 else None


def _state_for(connection):
    state = getattr(connection, _STATE, None)
    if state is None:
        state = _State()
        setattr(connection, _STATE, state)
    return state


async def _run_prefetch(gate, ticket, state, lang_tag_filter):
    try:
        status, result = await asyncio.to_thread(gate.prefetch, ticket)
        if status == "busy":
            state.counts["skipped_busy"] += 1
        elif status == "ready" and ticket.valid.is_set():
            # 复用当前已审查 FunASR 的同一标签清理函数，保留语言/情绪等字段。
            ticket.result = lang_tag_filter(result[0]["text"])
            if not isinstance(ticket.result, dict) or not ticket.result.get("content"):
                status = "empty"
                ticket.result = None
        ticket.status = status
    except asyncio.CancelledError:
        # 退出事件循环可以取消等待，但底层线程还可能在推理；结果永不提交。
        ticket.valid.clear()
        ticket.status = "invalidated"
        raise
    except Exception:
        ticket.status = "failed"
        ticket.result = None
        state.counts["failed"] += 1
    finally:
        if (state.generation == ticket.generation
                and ticket.started is not None and ticket.finished is not None):
            state.latest_prefetch_ms = round((ticket.finished - ticket.started) * 1000)
        if state.ticket is ticket:
            state.latest_status = ticket.status


def install_voice_asr_prefetch(connection_class, fun_local_module, *, enabled=False,
                               silence_ms=300, min_audio_seconds=1, max_audio_seconds=8):
    """只安装当前 fun_local 子类；默认关闭，重启时不安装即可完全回退。

调用方须传入已审查上游 ConnectionHandler 和 core.providers.asr.fun_local。
模型、预识别结果及计数均留在语音适配进程，长期记忆核心无需知道本功能。
"""
    if not enabled:
        return {"enabled": False, "installed": False}
    if not (200 <= silence_ms <= 500 and 0 < min_audio_seconds <= max_audio_seconds <= 8):
        raise ValueError("invalid_asr_prefetch_limits")
    provider_class = fun_local_module.ASRProvider
    if getattr(provider_class, "_longmemory_asr_prefetch_installed", False):
        return {"enabled": True, "installed": True}
    original_receive = provider_class.receive_audio
    original_handle = provider_class.handle_voice_stop
    original_speech = provider_class.speech_to_text
    original_reset = connection_class.reset_audio_states
    original_close = connection_class.close

    async def receive_audio(provider, connection, pcm_frame, audio_have_voice):
        eligible = _eligible(provider, connection)
        state = _state_for(connection) if eligible else getattr(connection, _STATE, None)
        if state is not None:
            stamp = _stamp(connection)
            if not eligible:
                state.invalidate("unsupported")
            elif stamp != state.voice_stamp or (audio_have_voice and state.ticket is not None):
                state.invalidate("speech_resumed")
                state.voice_stamp = stamp
        await original_receive(provider, connection, pcm_frame, audio_have_voice)
        # 上游在端点处会提交、清空音频；这里仅对尚未提交的标准 60ms/16k PCM 检查。
        if (not eligible or state.closed or state.attempted
                or audio_have_voice or connection.client_voice_stop
                or not connection.client_have_voice or _stamp(connection) is None
                or getattr(connection, "client_is_speaking", False)
                or not isinstance(pcm_frame, bytes) or len(pcm_frame) != 1920):
            return
        silence = time.time() * 1000 - _stamp(connection)
        if not silence_ms <= silence <= 2000:
            return
        audio = connection.asr_audio
        if len(audio) * 1920 > max_audio_seconds * 32000:
            return
        if not all(isinstance(frame, bytes) and len(frame) == 1920 for frame in audio):
            return
        size = sum(map(len, audio))
        if not min_audio_seconds * 32000 <= size <= max_audio_seconds * 32000:
            return
        state.attempted = True
        try:
            gate = _gate_for(provider)
        except Exception:
            state.counts["failed"] += 1
            state.latest_status = "unavailable"
            return
        ticket = _Ticket(b"".join(audio), state.generation, state.voice_stamp, provider.language)
        state.ticket = ticket
        state.counts["started"] += 1
        state.latest_status = "scheduled"
        ticket.task = asyncio.create_task(_run_prefetch(gate, ticket, state, fun_local_module.lang_tag_filter))

    async def handle_voice_stop(provider, connection, audio_task):
        state = getattr(connection, _STATE, None)
        if state is None or not _eligible(provider, connection):
            return await original_handle(provider, connection, audio_task)
        ticket = state.ticket
        state.latest_prefetch_ms = (
            round((ticket.finished - ticket.started) * 1000)
            if ticket is not None and ticket.started is not None and ticket.finished is not None else None
        )
        state.latest_formal_wait_ms = None
        state.latest_model_queue_ms = None
        state.latest_overlap_ms = None
        context = (connection, state, state.generation, _stamp(connection), time.perf_counter())
        token = _FORMAL.set(context)
        try:
            return await original_handle(provider, connection, audio_task)
        finally:
            _FORMAL.reset(token)

    async def speech_to_text(provider, pcm_data, session_id, artifacts=None):
        # 第一轮可能尚未触发预取；先让正式请求也接管同一模型锁，避免另一
        # 连接随后首次预取时，误以为已有的正式推理线程处于空闲状态。
        _gate_for(provider)
        context = _FORMAL.get()
        if context is None:
            return await original_speech(provider, pcm_data, session_id, artifacts)
        connection, state, generation, voice_stamp, endpoint = context
        ticket = state.ticket
        formal_pcm = getattr(artifacts, "pcm_bytes", b"")
        matches = (ticket is not None and ticket.valid.is_set()
                   and ticket.generation == generation and ticket.voice_stamp == voice_stamp
                   and ticket.language == provider.language and len(formal_pcm) >= ticket.size
                   and hashlib.sha256(formal_pcm[:ticket.size]).digest() == ticket.prefix_digest)
        if ticket is not None and not matches:
            state.invalidate("input_changed")
        if matches:
            started = time.perf_counter()
            await asyncio.shield(ticket.task)
            state.latest_formal_wait_ms = round((time.perf_counter() - started) * 1000)
            if (state.generation != generation or state.closed or connection.stop_event.is_set()):
                return "", None
            if (ticket.valid.is_set() and ticket.status == "ready" and ticket.result is not None
                    and _stamp(connection) == voice_stamp):
                state.counts["reused"] += 1
                state.latest_status = "reused"
                state.latest_model_queue_ms = 0
                state.latest_overlap_ms = max(0, round((min(endpoint, ticket.finished) - ticket.started) * 1000))
                result, ticket.result = ticket.result, None
                ticket.valid.clear()
                state.ticket = None
                return result, getattr(artifacts, "file_path", None)
        # 候选失效/空结果/失败时仍识别完整音频，不让半句话进入聊天或记忆。
        state.counts["fallback"] += 1
        metrics = {}
        token = _MODEL_WAIT.set(metrics)
        started = time.perf_counter()
        try:
            result = await original_speech(provider, pcm_data, session_id, artifacts)
        finally:
            _MODEL_WAIT.reset(token)
            state.latest_formal_wait_ms = round((time.perf_counter() - started) * 1000)
            state.latest_model_queue_ms = metrics.get("wait_ms", 0)
        if state.generation != generation or state.closed or connection.stop_event.is_set():
            return "", None
        return result

    def reset_audio_states(connection):
        state = getattr(connection, _STATE, None)
        if state is not None:
            state.invalidate("reset", reset=True)
        return original_reset(connection)

    async def close(connection, *args, **kwargs):
        state = getattr(connection, _STATE, None)
        if state is not None:
            state.closed = True
            state.invalidate("closed", reset=True)
        return await original_close(connection, *args, **kwargs)

    provider_class.receive_audio = receive_audio
    provider_class.handle_voice_stop = handle_voice_stop
    provider_class.speech_to_text = speech_to_text
    connection_class.reset_audio_states = reset_audio_states
    connection_class.close = close
    connection_class._longmemory_asr_prefetch_enabled = True
    connection_class._longmemory_asr_prefetch_snapshot = voice_asr_prefetch_snapshot
    provider_class._longmemory_asr_prefetch_installed = True
    return {"enabled": True, "installed": True, "silence_ms": silence_ms,
            "min_audio_seconds": min_audio_seconds, "max_audio_seconds": max_audio_seconds}
