"""为固定小智快照采集最近一轮首句时序，不保存任何对话正文。

本模块通过启动适配器包裹现有 LLM/TTS 调用，不修改第三方源码。所有时间都
相对于顶层 ``chat`` 入口；入口已经拿到 ASR 文本，因此这里不声称测量录音或
识别耗时。状态只保存在当前设备连接内存中，供本机控制桥读取。
"""

from datetime import UTC, datetime
import threading
import time


TIMING_FIELDS = (
    "memory_ready_ms",
    "llm_requested_ms",
    "llm_first_output_ms",
    "tts_started_ms",
    "audio_ready_ms",
    "first_audio_sent_ms",
    "response_completed_ms",
)


def _backend(connection):
    name = connection.config.get("selected_module", {}).get("TTS")
    if name == "EdgeTTS":
        return "edge"
    if name == "CustomTTS":
        return "voxcpm2"
    return "other"


def _has_output(value):
    """识别普通文本或工具调用流的首个有效增量，但不读取或记录其内容。"""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, tuple) and len(value) == 2:
        content, tools = value
        return (isinstance(content, str) and bool(content.strip())) or bool(tools)
    if isinstance(value, dict):
        return bool(value.get("content") or value.get("tool_calls"))
    return False


class VoiceLatencyTracker:
    """线程安全地保留单连接最近一轮数据；旧轮不会被迟到的音频覆盖。"""

    def __init__(self, connection, *, clock=time.perf_counter):
        self.connection = connection
        self.clock = clock
        self.lock = threading.Lock()
        self.current = None

    def begin(self):
        now = self.clock()
        with self.lock:
            self.current = {
                "version": 1,
                "sentence_id": None,
                "started_at": datetime.now(UTC).isoformat(),
                "started": now,
                "tts_backend": _backend(self.connection),
                "timings": {field: None for field in TIMING_FIELDS},
            }

    def bind_sentence(self):
        with self.lock:
            if self.current is not None and self.current["sentence_id"] is None:
                self.current["sentence_id"] = getattr(self.connection, "sentence_id", None)

    def mark(self, field, *, sentence_id=None):
        if field not in TIMING_FIELDS:
            raise ValueError("voice_latency_field_invalid")
        with self.lock:
            item = self.current
            if item is None or item["timings"][field] is not None:
                return
            expected = item["sentence_id"]
            if sentence_id is not None and expected is not None and sentence_id != expected:
                return
            elapsed = max(0, round((self.clock() - item["started"]) * 1000))
            item["timings"][field] = elapsed
        # 日志只含固定阶段名和毫秒数，不含问题、回答、记忆或音色提示词。
        self.connection.logger.bind(tag="voice-latency").info(
            f"圆屏首句计时 stage={field} elapsed={elapsed}ms"
        )

    def snapshot(self):
        with self.lock:
            if self.current is None:
                return None
            timings = dict(self.current["timings"])
            if timings["first_audio_sent_ms"] is not None:
                state = "first_audio_sent"
            elif timings["audio_ready_ms"] is not None:
                state = "audio_ready"
            elif timings["tts_started_ms"] is not None:
                state = "tts_running"
            elif timings["llm_first_output_ms"] is not None:
                state = "waiting_for_sentence"
            elif timings["llm_requested_ms"] is not None:
                state = "waiting_for_model"
            else:
                state = "preparing_memory"
            return {
                "version": 1,
                "state": state,
                "started_at": self.current["started_at"],
                "tts_backend": self.current["tts_backend"],
                "timings_ms": timings,
            }


def _observe_generator(connection, responses):
    for response in responses:
        if _has_output(response):
            connection._longmemory_voice_latency.mark("llm_first_output_ms")
        yield response


class _ObservedLLM:
    """连接私有代理；底层模型可共享，但计时归属不能共享。"""

    def __init__(self, connection, provider):
        self._connection = connection
        self._provider = provider

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def _call(self, method_name, *args, **kwargs):
        tracker = self._connection._longmemory_voice_latency
        tracker.bind_sentence()
        tracker.mark("llm_requested_ms")
        responses = getattr(self._provider, method_name)(*args, **kwargs)
        return _observe_generator(self._connection, responses)

    def response(self, *args, **kwargs):
        return self._call("response", *args, **kwargs)

    def response_with_functions(self, *args, **kwargs):
        return self._call("response_with_functions", *args, **kwargs)


def _observe_components(connection):
    """每个连接使用私有代理，避免把共享模型的阶段记到另一个设备。"""
    llm = getattr(connection, "llm", None)
    if llm is not None and not isinstance(llm, _ObservedLLM):
        connection.llm = _ObservedLLM(connection, llm)

    tts = getattr(connection, "tts", None)
    if tts is None or getattr(tts, "_longmemory_latency_observed", False):
        return
    original_stream = getattr(tts, "to_tts_stream", None)
    original_opus = getattr(tts, "handle_opus", None)
    if callable(original_stream):
        def measured_stream(*args, **kwargs):
            tracker = connection._longmemory_voice_latency
            tracker.bind_sentence()
            tracker.mark("tts_started_ms", sentence_id=getattr(tts, "current_sentence_id", None))
            return original_stream(*args, **kwargs)
        tts.to_tts_stream = measured_stream
    if callable(original_opus):
        def measured_opus(*args, **kwargs):
            tracker = connection._longmemory_voice_latency
            tracker.bind_sentence()
            tracker.mark("audio_ready_ms", sentence_id=getattr(tts, "current_sentence_id", None))
            return original_opus(*args, **kwargs)
        tts.handle_opus = measured_opus
    tts._longmemory_latency_observed = True


def install_voice_latency(connection_class):
    """在顶层回答入口建立计时轮次；递归工具调用仍属于同一轮。"""
    if getattr(connection_class, "_longmemory_latency_installed", False):
        return
    original = connection_class.chat

    def chat(connection, query, depth=0):
        if not hasattr(connection, "_longmemory_voice_latency"):
            connection._longmemory_voice_latency = VoiceLatencyTracker(connection)
        tracker = connection._longmemory_voice_latency
        if depth == 0:
            tracker.begin()
        _observe_components(connection)
        try:
            return original(connection, query, depth)
        finally:
            if depth == 0:
                tracker.bind_sentence()
                tracker.mark("response_completed_ms")

    connection_class.chat = chat
    connection_class._longmemory_latency_installed = True


def observed_audio_sender(original):
    """在现有发送协程真正返回后标记首包；空的 FIRST/LAST 控制帧不计。"""
    async def send(connection, sentence_type, audios, text, sentence_id=None):
        result = await original(connection, sentence_type, audios, text, sentence_id)
        has_audio = isinstance(audios, bytes) and bool(audios)
        has_audio = has_audio or (isinstance(audios, (list, tuple)) and len(audios) > 0)
        tracker = getattr(connection, "_longmemory_voice_latency", None)
        if has_audio and tracker is not None:
            tracker.bind_sentence()
            tracker.mark("first_audio_sent_ms", sentence_id=sentence_id)
        return result
    return send


def install_audio_send_observer():
    """包裹 TTS 基类已经导入的发送引用，不改写上游文件。"""
    from core.providers.tts import base
    if getattr(base, "_longmemory_audio_send_observed", False):
        return
    base.sendAudioMessage = observed_audio_sender(base.sendAudioMessage)
    base._longmemory_audio_send_observed = True
