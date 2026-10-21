"""连接内输入阶段计数；无逐帧日志、音频/文本/身份存储或行为调节。

AI 在既有包装之后安装并传入实际 ASR 子类。getter 不创建状态，不连接服务。
"""

from contextvars import ContextVar
import threading


STATE = "_longmemory_voice_input_observation"
LIMIT = 2 ** 31 - 1
KINDS = ("route", "handle", "receive", "formal", "speech", "abort")
COUNTERS = ("queue_put", "queue_get", "vad_check", "vad_speech", "vad_error",
            "route_no_enqueue", "just_woken_skipped", "stop_flag_receive", "stop_without_formal",
            "endpoint_length_rejected", "result_empty", "result_nonempty", "result_unknown", "observer_error") + tuple(
                kind + suffix for kind in KINDS for suffix in ("_begin", "_return", "_error", "_timeout", "_cancel"))
_ACTIVE = ContextVar("voice_input_observation_active", default=())
_ROUTE = ContextVar("voice_input_observation_route", default=None)
_HANDLE = ContextVar("voice_input_observation_handle", default=None)
_RECEIVE = ContextVar("voice_input_observation_receive", default=None)
_FORMAL = ContextVar("voice_input_observation_formal", default=None)


def _flags(connection):
    result = {name: value if type(value := getattr(connection, name, None)) is bool else None
              for name in ("client_aec", "client_is_speaking", "just_woken_up", "client_have_voice", "client_voice_stop")}
    mode = getattr(connection, "client_listen_mode", None)
    result["listen_mode"] = mode if isinstance(mode, str) and mode in {"auto", "realtime", "manual"} else "unknown"
    return result


class _State:
    def __init__(self):
        self.lock = threading.RLock()
        self.counts = {name: 0 for name in COUNTERS}
        self.active = {name: 0 for name in KINDS}
        self.saturated = False
        self.last_handle_flags = None
        self.endpoint_packet_count = None
        self.endpoint_pcm_bytes = None
        self.buffer_frames_before_receive = None
        self.formal_audio_frames = None
        self.formal_pcm_bytes = None
        self.failed = False

    def note(self, key):
        try:
            with self.lock:
                if self.counts[key] < LIMIT:
                    self.counts[key] += 1
                else:
                    self.saturated = True
        except Exception:
            self.failed = True

    def enter(self, kind):
        try:
            with self.lock:
                self.note(kind + "_begin")
                self.active[kind] = min(LIMIT, self.active[kind] + 1)
        except Exception:
            self.failed = True

    def leave(self, kind):
        try:
            with self.lock:
                self.active[kind] = max(0, self.active[kind] - 1)
        except Exception:
            self.failed = True


class _ObservedQueue:
    def __init__(self, original, state, connection):
        self.original, self.state, self.connection = original, state, connection

    def __getattr__(self, name):
        return getattr(self.original, name)

    def put(self, value, *args, **kwargs):
        result = self.original.put(value, *args, **kwargs)
        self.state.note("queue_put")
        current = _ROUTE.get()
        if current is not None and current[0] is self.connection:
            current[1]["enqueued"] = True
        return result

    def get(self, *args, **kwargs):
        result = self.original.get(*args, **kwargs)
        self.state.note("queue_get")
        return result

    def put_nowait(self, value):
        return self.put(value, block=False)

    def get_nowait(self):
        return self.get(block=False)


class _ObservedVAD:
    def __init__(self, original, state):
        self.original, self.state = original, state

    def __getattr__(self, name):
        return getattr(self.original, name)

    def is_vad(self, connection, frame):
        self.state.note("vad_check")
        try:
            result = self.original.is_vad(connection, frame)
        except BaseException:
            self.state.note("vad_error")
            raise
        if result:
            self.state.note("vad_speech")
        return result


def _attach_impl(connection):
    state = getattr(connection, STATE, None)
    if state is None:
        state = _State()
        setattr(connection, STATE, state)
    if not isinstance(state, _State):
        return None
    queue = getattr(connection, "asr_audio_queue", None)
    if queue is not None and not isinstance(queue, _ObservedQueue):
        try:
            connection.asr_audio_queue = _ObservedQueue(queue, state, connection)
        except Exception:
            state.note("observer_error")
    vad = getattr(connection, "vad", None)
    if vad is not None and not isinstance(vad, _ObservedVAD):
        try:
            connection.vad = _ObservedVAD(vad, state)
        except Exception:
            state.note("observer_error")
    return state


def _attach(connection):
    try:
        return _attach_impl(connection)
    except Exception:
        return None


def _missing(state):
    return {"version": 1, "state": state, "counts": None, "inflight": None, "queue_depth": None,
            "current_flags": None, "last_handle_flags": None, "endpoint_packet_count": None,
            "endpoint_pcm_bytes": None, "buffer_frames_before_receive": None,
            "formal_audio_frames": None, "formal_pcm_bytes": None, "counter_saturated": None,
            "value_kind": "connection_counters_not_audio_or_cpu_time"}


def _snapshot(connection):
    state = getattr(connection, STATE, None)
    if state is None:
        return _missing("no_connection" if connection is None else "not_observed")
    if not isinstance(state, _State) or state.failed:
        return _missing("unavailable")
    try:
        depth = connection.asr_audio_queue.qsize()
    except Exception:
        depth = None
    with state.lock:
        stop = getattr(connection, "stop_event", None)
        closed = callable(getattr(stop, "is_set", None)) and stop.is_set()
        return {"version": 1, "state": "closed" if closed else "observed", "counts": dict(state.counts),
                "inflight": dict(state.active), "counter_saturated": state.saturated,
                "queue_depth": min(LIMIT, depth) if type(depth) is int else None,
                "current_flags": _flags(connection),
                "last_handle_flags": dict(state.last_handle_flags) if state.last_handle_flags is not None else None,
                "endpoint_packet_count": state.endpoint_packet_count,
                "endpoint_pcm_bytes": state.endpoint_pcm_bytes,
                "buffer_frames_before_receive": state.buffer_frames_before_receive,
                "formal_audio_frames": state.formal_audio_frames,
                "formal_pcm_bytes": state.formal_pcm_bytes,
                "value_kind": "connection_counters_not_audio_or_cpu_time"}


def voice_input_observation_snapshot(connection):
    try:
        return _snapshot(connection)
    except Exception:
        return _missing("unavailable")


async def _call(connection, kind, action):
    if any(conn is connection and item == kind for conn, item in _ACTIVE.get()):
        return await action()
    state = _attach(connection)
    if state is None:
        return await action()
    token = _ACTIVE.set(_ACTIVE.get() + ((connection, kind),))
    state.enter(kind)
    try:
        result = await action()
        state.note(kind + "_return")
        return result
    except BaseException as error:
        import asyncio
        state.note(kind + ("_timeout" if isinstance(error, (TimeoutError, asyncio.TimeoutError)) else
                           "_cancel" if isinstance(error, asyncio.CancelledError) else "_error"))
        raise
    finally:
        state.leave(kind)
        _ACTIVE.reset(token)


def _provider_wrapper(original, kind):
    async def wrapped(provider, connection, *args, **kwargs):
        if any(conn is connection and item == kind for conn, item in _ACTIVE.get()):
            return await original(provider, connection, *args, **kwargs)
        state = _attach(connection)
        if state is None:
            return await original(provider, connection, *args, **kwargs)
        context = _HANDLE.get() if kind == "receive" else _RECEIVE.get()
        if context is not None and context[0] is connection:
            context[1]["seen"] = True
        marker = {"seen": False}
        if kind == "formal":
            frames = args[0] if args else kwargs.get("asr_audio_task")
            with state.lock:
                state.formal_audio_frames = min(LIMIT, len(frames)) if isinstance(frames, (list, tuple)) else None
                state.formal_pcm_bytes = min(LIMIT, sum(len(item) for item in frames)) if (
                    isinstance(frames, (list, tuple)) and all(isinstance(item, bytes) for item in frames)) else None
            if context is not None and context[0] is connection:
                data = context[1]
                if (data.get("expected_bytes") is not None and data.get("expected_bytes") == state.formal_pcm_bytes
                        and data.get("gate_eligible")):
                    state.endpoint_packet_count = data.get("expected_packets")
                    state.endpoint_pcm_bytes = state.formal_pcm_bytes
        context_var = _RECEIVE if kind == "receive" else _FORMAL
        value = (connection, marker) if kind == "receive" else connection
        token = context_var.set(value)
        stopped = kind == "receive" and getattr(connection, "client_voice_stop", False) is True
        length_gate_candidate = False
        if stopped:
            state.note("stop_flag_receive")
            audio = getattr(connection, "asr_audio", ())
            frame = args[0] if args else kwargs.get("pcm_frame")
            have_voice = args[1] if len(args) > 1 else kwargs.get("audio_have_voice", False)
            pcm_bytes = (sum(len(item) for item in audio) + len(frame)
                         if isinstance(audio, list) and all(isinstance(item, bytes) for item in audio)
                         and isinstance(frame, bytes) else None)
            with state.lock:
                state.buffer_frames_before_receive = min(LIMIT, len(audio))
                state.endpoint_packet_count = state.endpoint_pcm_bytes = None
                state.formal_audio_frames = state.formal_pcm_bytes = None
            gate_eligible = (
                getattr(connection, "client_listen_mode", None) in {"auto", "realtime"}
                and getattr(getattr(provider, "interface_type", None), "value", None) == "LOCAL"
                and (have_voice or getattr(connection, "client_have_voice", False)))
            marker.update(expected_packets=min(LIMIT, len(audio) + 1), expected_bytes=pcm_bytes,
                          gate_eligible=bool(gate_eligible))
            length_gate_candidate = gate_eligible and pcm_bytes is not None and pcm_bytes <= 1920 * 15
        try:
            result = await _call(connection, kind, lambda: original(provider, connection, *args, **kwargs))
            if stopped and not marker["seen"]:
                state.note("stop_without_formal")
                # 固定上游接收谓词 + 实际无formal调用 + 实际重置，才归为长度门拒绝。
                # manual/stream/纯噪声缓存和异常不混入该计数，不改源函数或15帧阈值。
                if (length_gate_candidate and getattr(connection, "client_voice_stop", None) is False
                        and len(getattr(connection, "asr_audio", ())) == 0):
                    state.note("endpoint_length_rejected")
                    state.endpoint_packet_count = marker["expected_packets"]
                    state.endpoint_pcm_bytes = marker["expected_bytes"]
            return result
        finally:
            context_var.reset(token)
    return wrapped


def _speech_wrapper(original):
    async def speech(provider, *args, **kwargs):
        connection = _FORMAL.get()
        if connection is None:
            return await original(provider, *args, **kwargs)
        nested = any(conn is connection and kind == "speech" for conn, kind in _ACTIVE.get())
        result = await _call(connection, "speech", lambda: original(provider, *args, **kwargs))
        if not nested:
            value = result[0] if isinstance(result, (tuple, list)) and result else result
            if isinstance(value, dict):
                value = value.get("content")
            category = ("nonempty" if value.strip() else "empty") if isinstance(value, str) else (
                "empty" if value is None else "unknown")
            state = _attach(connection)
            if state is not None:
                state.note("result_" + category)
        return result
    return speech


def install_voice_input_observation(connection_class, asr_base_module, receive_audio_module, *, asr_provider_classes=()):
    """在既有所有包装之后、连接启动前调用；传实际本地ASR子类，避免已捕获别名漏计。"""
    if getattr(connection_class, "_longmemory_input_observation_installed", False):
        return {"version": 1, "installed": True}
    original_route = connection_class._route_message

    async def route(connection, message):
        if not isinstance(message, bytes):
            return await original_route(connection, message)
        marker = {"enqueued": False}
        token = _ROUTE.set((connection, marker))
        try:
            result = await _call(connection, "route", lambda: original_route(connection, message))
            if not marker["enqueued"]:
                state = _attach(connection)
                if state is not None:
                    state.note("route_no_enqueue")
            return result
        finally:
            _ROUTE.reset(token)
    connection_class._route_message = route

    def audio_wrapper(original):
        async def handle(connection, frame):
            if any(conn is connection and kind == "handle" for conn, kind in _ACTIVE.get()):
                return await original(connection, frame)
            state = _attach(connection)
            if state is None:
                return await original(connection, frame)
            marker = {"seen": False}
            flags = _flags(connection)
            with state.lock:
                state.last_handle_flags = flags
            token = _HANDLE.set((connection, marker))
            try:
                result = await _call(connection, "handle", lambda: original(connection, frame))
                if flags["just_woken_up"] is True and not marker["seen"]:
                    state.note("just_woken_skipped")
                return result
            finally:
                _HANDLE.reset(token)
        return handle
    receive_handle = receive_audio_module.handleAudioMessage
    base_handle = asr_base_module.handleAudioMessage
    receive_audio_module.handleAudioMessage = audio_wrapper(receive_handle)
    asr_base_module.handleAudioMessage = (receive_audio_module.handleAudioMessage if base_handle is receive_handle else audio_wrapper(base_handle))
    original_abort = receive_audio_module.handleAbortMessage

    async def abort(connection, *args, **kwargs):
        return await _call(connection, "abort", lambda: original_abort(connection, *args, **kwargs))
    receive_audio_module.handleAbortMessage = abort
    classes = tuple(dict.fromkeys((asr_base_module.ASRProviderBase, *asr_provider_classes)))
    for cls in classes:
        cls.receive_audio = _provider_wrapper(cls.receive_audio, "receive")
        cls.handle_voice_stop = _provider_wrapper(cls.handle_voice_stop, "formal")
        if callable(getattr(cls, "speech_to_text", None)):
            cls.speech_to_text = _speech_wrapper(cls.speech_to_text)
    original_open = getattr(asr_base_module.ASRProviderBase, "open_audio_channels", None)
    if callable(original_open):
        async def open_audio(provider, connection):
            _attach(connection)
            return await original_open(provider, connection)
        asr_base_module.ASRProviderBase.open_audio_channels = open_audio
    connection_class._longmemory_voice_input_observation_snapshot = staticmethod(voice_input_observation_snapshot)
    connection_class._longmemory_input_observation_installed = True
    return {"version": 1, "installed": True, "specific_asr_classes": len(asr_provider_classes),
            "queue_before_worker": callable(original_open), "speech_results": "formal_context_only"}
