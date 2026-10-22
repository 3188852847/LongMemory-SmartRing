"""Cosy输出的进程内撤权：ASR交接即撤销旧轮，不依赖可复位的abort布尔。

不识别文本意图、不运行VAD/ASR/AEC、不保存正文或PCM。正式输入继续交给原上游。
状态接口只提供时序/计数；stop发出或队列空不等于设备已经静音。
"""

import asyncio
from collections import Counter, deque
from contextvars import ContextVar
from contextlib import nullcontext
import inspect
import threading
import time
from voice_waiting import WaitingPacket, AnswerPacket


STATE = "_longmemory_audio_interruption"
_ABORT = ContextVar("cosy_abort_epoch_context", default=None)
_EOS_INPUT = ContextVar("cosy_eos_input_target", default=None)
_CONTROL = ContextVar("cosy_control_epoch_context", default=None)
_HANDOFF = ContextVar("cosy_handoff_context", default=None)
_MESSAGE = ContextVar("cosy_message_epoch_context", default=None)
_STATES_LOCK = threading.Lock()
COUNTERS = (
    "asr_handoff", "asr_handoff_revoked", "upstream_abort_revoked", "queues_cleared",
    "abort_call_returned", "connection_closed", "tts_started", "tts_returned",
    "first_segment_callback_returned", "first_answer_send_returned", "answer_send_returned",
    "cue_send_returned", "stale_packet_dropped", "inflight_old_send_returned",
    "stale_message_dropped", "stale_stop_dropped", "normal_stop_returned",
    "producer_adaptive_buffer", "producer_incremental_pcm", "producer_buffered_pcm",
    "producer_preset", "producer_complete_wav_fallback",
)


def _configuration(connection):
    mode = getattr(connection, "_longmemory_cosy_delivery_mode", "unknown")
    return {"delivery_mode": (mode if isinstance(mode, str) and mode in {"buffered", "incremental", "adaptive"} else "unknown")
            if supported(connection) else None, "value_kind": "configuration"}


def supported(connection):
    if getattr(getattr(connection, "tts", None), "_longmemory_cosy_streaming_installed", False):
        return True
    config = getattr(connection, "config", {})
    if not isinstance(config, dict):
        return False
    selected = config.get("selected_module")
    engines = config.get("TTS")
    custom = engines.get("CustomTTS") if isinstance(engines, dict) else None
    return (isinstance(selected, dict) and selected.get("TTS") == "CustomTTS"
            and isinstance(custom, dict)
            and custom.get("url") == "http://127.0.0.1:18770/v1/audio/speech")


class OutputState:
    def __init__(self, connection):
        self.connection = connection
        self.lock = threading.RLock()
        self.epoch = 0
        self.closed = self.active = False
        self.producers = 0
        self.revoked = deque(maxlen=64)
        self.counts = Counter()
        self.events = deque(maxlen=32)
        self.started = time.perf_counter()
        self.last_first_send = None
        self.observed = None

    def note(self, event, *, record=True):
        if event not in COUNTERS:
            raise ValueError("audio_interruption_event_invalid")
        with self.lock:
            self.counts[event] += 1
            if record:
                self.events.append({"event": event, "at_ms": round((time.perf_counter() - self.started) * 1000),
                                    "epoch": self.epoch})

    def revoke(self, reason):
        with self.lock:
            waiting = getattr(self.connection, "_longmemory_waiting", None)
            self.epoch += 1
            self.active = False
            for sentence in (getattr(self.connection, "sentence_id", None),
                             getattr(getattr(self.connection, "tts", None), "current_sentence_id", None)):
                if sentence is not None and sentence not in self.revoked:
                    self.revoked.append(sentence)
            self.note(reason)
            protocol = getattr(self.connection, "_longmemory_tts_interrupt_wire", None)
            if protocol is not None:
                protocol.revoke(reason)
        cancel = getattr(waiting, "cancel", None)
        if callable(cancel):
            cancel()  # timer/已排队提示也永久失效，不能随client_abort=False复活。

    def snapshot(self):
        with self.lock:
            installed = getattr(self.connection, "_longmemory_audio_revocation_installed", False) is True
            return {"version": 1, "enabled": supported(self.connection), "epoch": self.epoch,
                    "connection_present": True, "installed": installed,
                    "status": "not_installed" if not installed else ("observed" if self.counts else "idle_no_samples"),
                    "active_output": self.active, "active_tts_calls": self.producers,
                    "closed": self.closed, "counts": {key: self.counts.get(key, 0) for key in COUNTERS},
                    "last_stage": dict(self.events[-1]) if self.events else None,
                    "configuration": _configuration(self.connection),
                    "observed": None if self.observed is None else dict(self.observed),
                    "device_playback_acknowledged": False}

    def producer(self, path, request_mode=None, *, lease):
        if "producer_" + path not in COUNTERS:
            raise ValueError("audio_interruption_producer_invalid")
        with self.lock:
            if not lease.current():
                return
            self.observed = {"value_kind": "observed_client_branch", "producer_path": path,
                "request_delivery_mode": request_mode, "v2_transport_confirmed": False,
                "server_model_delivery_mode": "unconfirmed", "server_reply_cache_hit": "unconfirmed"}
            self.note("producer_" + path)


def snapshot(connection):
    state = getattr(connection, STATE, None)
    if state is not None:
        return state.snapshot()
    installed = getattr(connection, "_longmemory_audio_revocation_installed", False) is True
    return {"version": 1, "enabled": supported(connection), "connection_present": connection is not None,
            "installed": installed, "status": "no_connection" if connection is None else (
                "idle_no_samples" if installed else "not_installed"),
            "epoch": 0 if connection is not None else None, "active_output": False,
            "active_tts_calls": 0, "closed": False, "configuration": _configuration(connection),
            "observed": None, "counts": {key: 0 for key in COUNTERS}, "last_stage": None,
            "device_playback_acknowledged": False}


def state_for(connection):
    with _STATES_LOCK:
        state = getattr(connection, STATE, None)
        if state is None:
            state = OutputState(connection)
            setattr(connection, STATE, state)
        return state


class OutputLease:
    def __init__(self, connection, sentence_id, *, producing=False):
        self.state = state_for(connection)
        self.sentence_id = sentence_id
        self.producing = producing
        self.released = False
        with self.state.lock:
            self.epoch = self.state.epoch
            if producing and self.current():
                self.state.active = True
                self.state.producers += 1
                self.state.note("tts_started")
            else:
                self.producing = False
        protocol = getattr(connection, "_longmemory_tts_interrupt_wire", None)
        self.wire_turn = protocol.capture_turn() if protocol is not None else None

    def current(self):
        state = self.state
        with state.lock:
            current = getattr(state.connection, "sentence_id", self.sentence_id)
            wire_turn = getattr(self, "wire_turn", None)
            protocol = getattr(state.connection, "_longmemory_tts_interrupt_wire", None)
            return (not state.closed and self.epoch == state.epoch
                    and self.sentence_id not in state.revoked
                    and (self.sentence_id is None or self.sentence_id == current)
                    and (protocol is None or not protocol.closed)
                    and (wire_turn is None or wire_turn.identity_current()))

    def release(self):
        with self.state.lock:
            if self.producing and not self.released:
                self.state.producers -= 1
                self.state.note("tts_returned")
            self.released = True
            # 返回只表示生产/交付结束；播放器可能仍有积压，不能在这里清active。


def revoked_sentence(connection, sentence_id):
    state = getattr(connection, STATE, None)
    if state is None or sentence_id is None:
        return False
    with state.lock:
        return sentence_id in state.revoked


def current_output_lease(connection):
    lease = _CONTROL.get() or _MESSAGE.get()
    if lease is not None and lease.state.connection is connection:
        return lease
    protocol = getattr(connection, "_longmemory_tts_interrupt_wire", None)
    return protocol.current_lease() if protocol is not None else None


class _StaleControl(Exception):
    pass


class _ControlPacket(bytes):
    def __new__(cls, value, lease):
        # 只叠加撤权元数据，不抹去答案/等待类别；下游过滤和首包计时仍需它。
        if isinstance(value, AnswerPacket):
            packet = AnswerPacket(value, value.state)
        elif isinstance(value, WaitingPacket):
            packet = WaitingPacket(value, value.state)
        else:
            packet = super().__new__(cls, value)
        original_cancelled = getattr(value, "_longmemory_cosy_cancelled", None)
        packet._longmemory_cosy_sentence_id = lease.sentence_id
        packet._longmemory_cosy_cancelled = lambda: (not lease.current()
            or (callable(original_cancelled) and original_cancelled()))
        packet._longmemory_output_lease = getattr(value, "_longmemory_output_lease", lease)
        packet._longmemory_send_receipt = getattr(value, "_longmemory_send_receipt", None)
        return packet


def _install_eos_vad_interruption(receive_module, asr_base_module):
    """只补EOS后的既有VAD阳性路径；固定单包目标，等待中出现的新轮不可撤销。"""
    original_no_voice = getattr(receive_module, "no_voice_close_connect", None)
    original_handle = getattr(receive_module, "handleAudioMessage", None)
    if (not inspect.iscoroutinefunction(original_no_voice)
            or not inspect.iscoroutinefunction(original_handle)
            or getattr(original_no_voice, "_longmemory_eos_vad_wrapped", False)):
        return

    def input_handler(original):
        if getattr(original, "_longmemory_eos_input_wrapped", False):
            return original
        async def handle(connection, *args, **kwargs):
            prior = _EOS_INPUT.get()
            if prior is not None and prior[0] is connection:
                return await original(connection, *args, **kwargs)
            protocol = getattr(connection, "_longmemory_tts_interrupt_wire", None)
            turn = getattr(protocol, "turn", None)
            target = (connection, None, None)
            if (supported(connection) and getattr(connection, "client_aec", False) is True
                    and getattr(connection, "client_listen_mode", None) != "manual"
                    and getattr(connection, "client_is_speaking", None) is False
                    and turn is not None and turn.eos and protocol.has_interrupt_target()):
                target = (connection, protocol, turn)
            token = _EOS_INPUT.set(target)
            try:
                return await original(connection, *args, **kwargs)
            finally:
                _EOS_INPUT.reset(token)
        handle._longmemory_eos_input_wrapped = True
        return handle

    original = original_handle
    alias = getattr(asr_base_module, "handleAudioMessage", None)
    receive_module.handleAudioMessage = input_handler(original)
    if alias is not None:
        asr_base_module.handleAudioMessage = (receive_module.handleAudioMessage if alias is original
                                             else input_handler(alias))

    async def no_voice_close_connect(connection, have_voice):
        target = _EOS_INPUT.get()
        if target is not None and target[0] is connection and have_voice is True:
            _, protocol, turn = target
            # 原handle已跑过一次VAD、唤醒忽略和原快速abort。只处理捕获的EOS目标；
            # 等待期间若目标已撤销或被新轮替换，不能再次撤权。
            if (protocol is not None
                    and getattr(connection, "_longmemory_tts_interrupt_wire", None) is protocol
                    and protocol.turn is turn and turn.eos and protocol.has_interrupt_target()
                    and supported(connection) and getattr(connection, "client_aec", False) is True
                    and getattr(connection, "client_listen_mode", None) != "manual"):
                await receive_module.handleAbortMessage(connection)
        # 保留结束提示/持久会话等既有包装的返回值、异常和调用顺序。
        return await original_no_voice(connection, have_voice)
    no_voice_close_connect._longmemory_eos_vad_wrapped = True
    receive_module.no_voice_close_connect = no_voice_close_connect


def install_voice_interruption(connection_class, receive_module, asr_base_module, send_module, *, tts_base_module):
    """上游模块须由启动器传入；不在此加载模型，保留不同导入别名的原包装。"""
    _install_eos_vad_interruption(receive_module, asr_base_module)
    if not getattr(connection_class, "_longmemory_audio_revocation_installed", False):
        original_clear = connection_class.clear_queues
        def clear(connection, *args, **kwargs):
            if supported(connection) and getattr(connection, "client_abort", False):
                state = state_for(connection)
                context = _ABORT.get()
                if context is None or context[0] is not connection or context[1] != state.epoch:
                    state.revoke("upstream_abort_revoked")
                state.note("queues_cleared")
            return original_clear(connection, *args, **kwargs)
        connection_class.clear_queues = clear
        original_close = getattr(connection_class, "close", None)
        if inspect.iscoroutinefunction(original_close):
            async def close(connection, *args, **kwargs):
                if supported(connection):
                    state = state_for(connection)
                    state.revoke("connection_closed")
                    state.closed = True
                return await original_close(connection, *args, **kwargs)
            connection_class.close = close
        connection_class._longmemory_audio_interruption_snapshot = snapshot
        connection_class._longmemory_audio_revocation_installed = True

    def wrap_handoff(original):
        if getattr(original, "_longmemory_audio_handoff_wrapped", False):
            return original
        async def handoff(connection, text):
            if _HANDOFF.get() is connection:
                return await original(connection, text)
            handoff_token = _HANDOFF.set(connection)
            try:
                protocol = getattr(connection, "_longmemory_tts_interrupt_wire", None)
                eligible = (protocol is not None and supported(connection) and isinstance(text, str)
                    and text.strip() and not getattr(connection, "need_bind", False)
                    and getattr(connection, "client_listen_mode", None) != "manual"
                    and not getattr(connection, "calling", False))
                with protocol.input_scope() if eligible else nullcontext():
                    try:
                        return await handoff_once(connection, text)
                    except Exception as error:
                        if protocol is not None and protocol.is_stale_error(error):
                            return None
                        raise
            finally:
                _HANDOFF.reset(handoff_token)
        async def handoff_once(connection, text):
            if (supported(connection) and isinstance(text, str) and text.strip()
                    and not getattr(connection, "need_bind", False)):
                state = state_for(connection)
                state.note("asr_handoff")
                protocol = getattr(connection, "_longmemory_tts_interrupt_wire", None)
                # speaking布尔可能已被迟到stop清除；生产/播放生命周期才是额外依据。
                if (getattr(connection, "client_listen_mode", None) != "manual"
                        and not getattr(connection, "calling", False)
                        and (state.active or getattr(connection, "client_is_speaking", False)
                             or (protocol is not None and protocol.has_interrupt_target()))):
                    state.revoke("asr_handoff_revoked")
                    token = _ABORT.set((connection, state.epoch))
                    try:
                        await receive_module.handleAbortMessage(connection)
                        state.note("abort_call_returned")
                    finally:
                        _ABORT.reset(token)
            return await original(connection, text)
        handoff._longmemory_audio_handoff_wrapped = True
        return handoff
    original_receive_start = receive_module.startToChat
    original_asr_start = asr_base_module.startToChat
    receive_module.startToChat = wrap_handoff(original_receive_start)
    asr_base_module.startToChat = (receive_module.startToChat if original_asr_start is original_receive_start
                                 else wrap_handoff(original_asr_start))

    if getattr(send_module, "_longmemory_audio_control_epoch_installed", False):
        return {"version": 1, "installed": True, "requires_preemptive": False,
                "device_playback_acknowledged": False}
    original_tts = send_module.send_tts_message
    original_wait = send_module._wait_for_audio_completion
    original_audio = send_module.sendAudio
    original_packet = send_module._do_send_audio

    async def wait_completion(connection):
        lease = current_output_lease(connection)
        if lease is None:
            return await original_wait(connection)
        task = asyncio.create_task(original_wait(connection))
        try:
            while not task.done():
                if not lease.current():
                    raise _StaleControl()
                await asyncio.wait({task}, timeout=.02)
            result = await task
            if not lease.current():
                raise _StaleControl()
            return result
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def send_tts(connection, state, text=None):
        message_lease = _MESSAGE.get()
        if message_lease is not None and not message_lease.current():
            message_lease.state.note("stale_message_dropped", record=False)
            return None
        if state != "stop" or not supported(connection):
            return await original_tts(connection, state, text)
        lease = message_lease or OutputLease(connection, getattr(connection, "sentence_id", None))
        if not lease.current() or getattr(connection, "client_abort", False):
            lease.state.note("stale_stop_dropped")
            return None
        token = _CONTROL.set(lease)
        try:
            try:
                result = await original_tts(connection, state, text)
            except _StaleControl:
                lease.state.note("stale_stop_dropped")
                return None
            if lease.current():
                lease.state.active = False
                lease.state.note("normal_stop_returned")
            return result
        finally:
            _CONTROL.reset(token)

    async def send_audio(connection, audios, *args, **kwargs):
        lease = _CONTROL.get() or _MESSAGE.get()
        if lease is not None and audios:
            if not lease.current():
                return None
            audios = (_ControlPacket(audios, lease) if isinstance(audios, bytes)
                      else [_ControlPacket(packet, lease) for packet in audios])
        return await original_audio(connection, audios, *args, **kwargs)

    async def send_packet(connection, packet, flow_control):
        if not supported(connection):
            return await original_packet(connection, packet, flow_control)
        state = state_for(connection)
        stale = getattr(packet, "_longmemory_cosy_cancelled", None)
        packet_state = getattr(packet, "state", None)
        packet_current = getattr(packet_state, "current", None)
        if ((callable(stale) and stale()) or (callable(packet_current) and not packet_current())
                or revoked_sentence(connection, flow_control.get("sentence_id"))):
            state.note("stale_packet_dropped", record=False)
            return None
        before = flow_control.get("packet_count", 0)
        receipt = getattr(packet, "_longmemory_send_receipt", None)
        previously_sent = receipt is not None and receipt.sent_at is not None
        send_epoch = state.epoch
        result = await original_packet(connection, packet, flow_control)
        confirmed = (receipt.sent_at is not None and not previously_sent) if receipt is not None else (
            flow_control.get("packet_count", 0) > before)
        if confirmed:
            with state.lock:
                if send_epoch != state.epoch or revoked_sentence(connection, flow_control.get("sentence_id")):
                    state.note("inflight_old_send_returned")
                elif isinstance(packet, WaitingPacket) and not isinstance(packet, AnswerPacket):
                    state.note("cue_send_returned", record=False)
                else:
                    state.active = True
                    key = (state.epoch, flow_control.get("sentence_id"))
                    if key != state.last_first_send:
                        state.last_first_send = key
                        state.note("first_answer_send_returned")
                    state.note("answer_send_returned", record=False)
        return result

    def wrap_message(original):
        async def message(connection, sentence_type, audios, text, sentence_id=None):
            if not supported(connection):
                return await original(connection, sentence_type, audios, text, sentence_id)
            lease = _MESSAGE.get() or OutputLease(connection,
                sentence_id if sentence_id is not None else getattr(connection, "sentence_id", None))
            if not lease.current():
                lease.state.note("stale_message_dropped", record=False)
                return None
            token = _MESSAGE.set(lease)
            try:
                return await original(connection, sentence_type, audios, text, sentence_id)
            finally:
                _MESSAGE.reset(token)
        return message

    send_module._wait_for_audio_completion = wait_completion
    send_module.send_tts_message = send_tts
    send_module.sendAudio = send_audio
    send_module._do_send_audio = send_packet
    previous_message = send_module.sendAudioMessage
    send_module.sendAudioMessage = wrap_message(previous_message)
    tts_base_module.sendAudioMessage = (send_module.sendAudioMessage
        if tts_base_module.sendAudioMessage is previous_message else wrap_message(tts_base_module.sendAudioMessage))
    send_module._longmemory_audio_control_epoch_installed = True
    return {"version": 1, "installed": True, "requires_preemptive": False,
            "device_playback_acknowledged": False}
