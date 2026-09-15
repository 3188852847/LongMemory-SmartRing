"""为固定小智快照采集最近一轮首句时序，不保存任何对话正文。

本模块通过启动适配器包裹现有 LLM/TTS 调用，不修改第三方源码。所有时间都
相对于顶层 ``chat`` 入口；入口已经拿到 ASR 文本，因此这里不声称测量录音或
识别耗时。状态只保存在当前设备连接内存中，供本机控制桥读取。
"""

from datetime import datetime, timezone
import threading
import time

from cosyvoice_segments import (
    install_cosyvoice_punctuation_policy,
    install_cosyvoice_ready_segment_drain,
)
from voice_response_policy import prepare_voice_dialogue
from voice_waiting import WaitingPacket, AnswerPacket, begin_waiting, mark_answer_ready


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
        url = connection.config.get("TTS", {}).get("CustomTTS", {}).get("url")
        return {
            "http://127.0.0.1:18768/v1/audio/speech": "voxcpm2",
            "http://127.0.0.1:18769/v1/audio/speech": "sanotts",
            "http://127.0.0.1:18770/v1/audio/speech": "cosyvoice3",
        }.get(url, "other")
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
        self.last_audible = None
        self.sequence = 0

    @staticmethod
    def _snapshot_item(item):
        timings = dict(item["timings"])
        if item["failure"] is not None:
            state = "failed"
        elif timings["first_audio_sent_ms"] is not None:
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
        result = {
            "version": item["version"],
            "state": state,
            "started_at": item["started_at"],
            "tts_backend": item["tts_backend"],
            "response_path": item["response_path"],
            "timings_ms": timings,
            "tts_segments": [dict(segment) for segment in item["tts_segments"]],
        }
        if item.get("input_timings_ms") is not None:
            result["input_timings_ms"] = dict(item["input_timings_ms"])
        if item["failure"] is not None:
            result["failure"] = dict(item["failure"])
        return result

    def begin(self):
        now = self.clock()
        pending = getattr(self.connection, "_longmemory_voice_input_pending", None)
        self.connection.__dict__.pop("_longmemory_voice_input_pending", None)
        input_timings = None
        if (
            isinstance(pending, dict)
            and type(pending.get("expires_at")) in {int, float}
            and now <= pending["expires_at"]
            and isinstance(pending.get("input_timings_ms"), dict)
        ):
            input_timings = dict(pending["input_timings_ms"])
        with self.lock:
            self.sequence += 1
            self.current = {
                "version": 6,
                # token 只在进程内用于拒绝上一轮迟到的 finally 回调，绝不暴露给 API。
                "token": self.sequence,
                # chat() 会在进入上游实现后才生成新 sentence_id。记录旧值可防止
                # 上一轮尚未结束的 Memory/TTS 回调抢先绑定到刚开始的新样本。
                "previous_sentence_id": getattr(self.connection, "sentence_id", None),
                "sentence_id": None,
                # 小智当前独立环境仍是 Python 3.10；timezone.utc 在该版本可用，
                # 不能使用 Python 3.11 才加入的 datetime.UTC 别名。
                "started_at": datetime.now(timezone.utc).isoformat(),
                "started": now,
                "tts_backend": _backend(self.connection),
                "response_path": "model",
                "input_timings_ms": input_timings,
                "timings": {field: None for field in TIMING_FIELDS},
                # 只保留固定阶段、分类码和相对时间，绝不把供应商响应正文、
                # 请求内容、地址或密钥暴露给控制台。
                "failure": None,
                # 每个元素只记录顺序与时间，不保存本段文本或音频。短句模型具有
                # 固定启动开销时，这能区分“首段慢”和“每段都慢”。
                "tts_segments": [],
            }
            return self.sequence

    def set_response_path(self, value):
        """标记封闭的回答路径，不保存输入、回答或命中规则。"""
        if value not in {"model", "preset"}:
            raise ValueError("voice_response_path_invalid")
        with self.lock:
            if self.current is not None:
                self.current["response_path"] = value

    def fail(self, code, *, stage="model"):
        allowed = {
            "model": {
                "model_http_404", "model_http_error", "model_connection_failed",
                "model_timeout", "model_request_failed",
            },
            "memory": {"memory_response_invalid", "memory_runtime_failed"},
        }
        if stage not in allowed or code not in allowed[stage]:
            raise ValueError("voice_failure_invalid")
        with self.lock:
            item = self.current
            if item is None or item["failure"] is not None:
                return
            elapsed = max(0, round((self.clock() - item["started"]) * 1000))
            item["failure"] = {"stage": stage, "code": code, "at_ms": elapsed}
        self.connection.logger.bind(tag="voice-latency").error(
            f"圆屏回答失败 stage={stage} code={code} elapsed={elapsed}ms"
        )

    def bind_sentence(self, sentence_id=None):
        with self.lock:
            if self.current is None or self.current["sentence_id"] is not None:
                return
            candidate = sentence_id
            if candidate is None:
                candidate = getattr(self.connection, "sentence_id", None)
            if candidate is None or candidate == self.current["previous_sentence_id"]:
                return
            self.current["sentence_id"] = candidate

    def mark(self, field, *, sentence_id=None, token=None):
        if field not in TIMING_FIELDS:
            raise ValueError("voice_latency_field_invalid")
        with self.lock:
            item = self.current
            if item is None or item["timings"][field] is not None:
                return
            if token is not None and token != item["token"]:
                return
            expected = item["sentence_id"]
            if sentence_id is not None:
                # 显式带句子归属的异步回调必须等当前样本完成绑定；否则上一轮
                # 的迟到回调会在 expected=None 时被误收为当前轮数据。
                if expected is None or sentence_id != expected:
                    return
            elapsed = max(0, round((self.clock() - item["started"]) * 1000))
            item["timings"][field] = elapsed
            if item["timings"]["first_audio_sent_ms"] is not None:
                self.last_audible = self._snapshot_item(item)
        # 日志只含固定阶段名和毫秒数，不含问题、回答、记忆或音色提示词。
        self.connection.logger.bind(tag="voice-latency").info(
            f"圆屏首句计时 stage={field} elapsed={elapsed}ms"
        )

    def begin_tts_segment(self, *, sentence_id=None):
        """开始一段脱敏 TTS 计时，返回只在当前进程内使用的句柄。"""
        with self.lock:
            item = self.current
            if item is None:
                return None
            expected = item["sentence_id"]
            if sentence_id is not None and (expected is None or sentence_id != expected):
                return None
            elapsed = max(0, round((self.clock() - item["started"]) * 1000))
            index = len(item["tts_segments"]) + 1
            item["tts_segments"].append({
                "index": index,
                "started_ms": elapsed,
                "completed_ms": None,
                "duration_ms": None,
                # Xiaozhi 当前链路固定使用 60ms Opus 帧。计数足以推导可播放
                # 时长，同时不会保留语音、文本或编码数据。
                "opus_packets": 0,
                "audio_duration_ms": 0,
            })
            if item["timings"]["tts_started_ms"] is None:
                item["timings"]["tts_started_ms"] = elapsed
            return item["token"], index

    def record_tts_audio_packet(self, handle, *, sentence_id=None):
        """给所属 TTS 片段累计一帧 60ms Opus 音频。"""
        if handle is None:
            return
        token, index = handle
        with self.lock:
            item = self.current
            if item is None or token != item["token"]:
                return
            expected = item["sentence_id"]
            if sentence_id is not None and (expected is None or sentence_id != expected):
                return
            if not 1 <= index <= len(item["tts_segments"]):
                return
            segment = item["tts_segments"][index - 1]
            segment["opus_packets"] += 1
            segment["audio_duration_ms"] = segment["opus_packets"] * 60

    def complete_tts_segment(self, handle, *, sentence_id=None):
        """完成当前段计时；上一轮迟到的回调不能写入新一轮。"""
        if handle is None:
            return
        token, index = handle
        with self.lock:
            item = self.current
            if item is None or token != item["token"]:
                return
            expected = item["sentence_id"]
            if sentence_id is not None and (expected is None or sentence_id != expected):
                return
            if not 1 <= index <= len(item["tts_segments"]):
                return
            segment = item["tts_segments"][index - 1]
            if segment["completed_ms"] is not None:
                return
            elapsed = max(0, round((self.clock() - item["started"]) * 1000))
            segment["completed_ms"] = elapsed
            segment["duration_ms"] = max(0, elapsed - segment["started_ms"])
            if item["timings"]["first_audio_sent_ms"] is not None:
                self.last_audible = self._snapshot_item(item)
        self.connection.logger.bind(tag="voice-latency").info(
            f"圆屏分段计时 segment={index} duration={segment['duration_ms']}ms"
        )

    def snapshot(self):
        with self.lock:
            if self.current is None:
                return None
            # 心跳、空识别或未进入模型的轮次可能紧随真实回答开始。控制面优先返回
            # 最近一次已经发出音频的样本，避免可诊断的慢回答被空轮次覆盖。
            if (self.current["failure"] is not None
                    or self.current["timings"]["first_audio_sent_ms"] is not None):
                return self._snapshot_item(self.current)
            if self.last_audible is not None:
                return {
                    **self.last_audible,
                    "timings_ms": dict(self.last_audible["timings_ms"]),
                    "tts_segments": [
                        dict(segment) for segment in self.last_audible["tts_segments"]
                    ],
                }
            return self._snapshot_item(self.current)


def install_first_chunk_policy(tts, *, maximum_chars, marker):
    """让首个无标点长片段提前进入合成，后续切句保持上游行为。

    这项策略只消费回答模型已经输出的文字，不预测或改写回答。它缩短
    “模型已有足够文字但 TTS 仍在等标点”的空等时间，并且只拆第一段，
    避免整段回答被机械地按固定字数切碎。
    """
    if maximum_chars < 8:
        raise ValueError("first_chunk_limit_invalid")
    installed = getattr(tts, "_longmemory_first_chunk_policies", set())
    if marker in installed:
        return
    original = getattr(tts, "_get_segment_text", None)
    if not callable(original):
        return

    def get_segment_text():
        segment = original()
        if segment is not None or not getattr(tts, "is_first_sentence", False):
            return segment
        full_text = "".join(getattr(tts, "tts_text_buff", ()))
        processed = getattr(tts, "processed_chars", 0)
        current = full_text[processed:]
        if len(current) < maximum_chars:
            return None
        # 中文语音以字符为稳定边界；若恰好处于 ASCII 单词中，则向前寻找空格，
        # 避免把 URL 或英文词拆成两个难以朗读的片段。
        end = maximum_chars
        if (end < len(current) and current[end - 1].isascii()
                and current[end - 1].isalnum() and current[end].isascii()
                and current[end].isalnum()):
            boundary = current.rfind(" ", 0, end)
            if boundary >= 8:
                end = boundary + 1
        raw = current[:end]
        tts.processed_chars += len(raw)
        tts.is_first_sentence = False
        return raw.strip()

    tts._get_segment_text = get_segment_text
    tts._longmemory_first_chunk_policies = {*installed, marker}


def install_edge_first_chunk_policy(tts, *, maximum_chars=18):
    """Edge 首段仍使用原有 18 字保守阈值。"""
    install_first_chunk_policy(
        tts, maximum_chars=maximum_chars, marker="edge"
    )


def _model_failure_code(error):
    status = getattr(error, "status_code", None)
    if status == 404:
        return "model_http_404"
    if isinstance(status, int):
        return "model_http_error"
    name = type(error).__name__.lower()
    if "timeout" in name:
        return "model_timeout"
    if "connection" in name:
        return "model_connection_failed"
    return "model_request_failed"


def _observe_generator(connection, responses, waiting=None):
    produced_output = False
    try:
        for response in responses:
            if waiting is not None and not waiting.current():
                return
            if _has_output(response):
                produced_output = True
                connection._longmemory_voice_latency.mark("llm_first_output_ms")
            yield response
    except Exception as error:
        is_current = waiting is None or waiting.current()
        if waiting is not None:
            waiting.cancel()
        if is_current:
            connection._longmemory_voice_latency.fail(_model_failure_code(error))
        raise
    finally:
        if waiting is not None and not produced_output:
            waiting.cancel()  # 空回答不能在 LAST 之后才补出一条迟到提示。
        close = getattr(responses, "close", None)
        if callable(close):
            close()


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
        # 只在圆屏本次请求中鼓励尽早形成可朗读的完整首句。共享 provider、
        # 网页角色和原会话消息均不修改；两条流式接口使用同一表达策略。
        if len(args) >= 2:
            dialogue = begin_waiting(self._connection, args[1])
            if dialogue is None:
                return iter(())
            args = (args[0], prepare_voice_dialogue(dialogue), *args[2:])
        elif "dialogue" in kwargs:
            dialogue = begin_waiting(self._connection, kwargs["dialogue"])
            if dialogue is None:
                return iter(())
            kwargs = {**kwargs, "dialogue": prepare_voice_dialogue(dialogue)}
        # 首次模型请求同时决定是否搜索；工具查询和最终答案另行计时。
        tracker.mark("llm_requested_ms")
        try:
            waiting = getattr(self._connection, "_longmemory_waiting", None)
            if method_name == "response" and waiting is not None and waiting.current():
                from voice_web_search import web_response
                responses = web_response(self._connection, self._provider, *args, **kwargs)
            else:
                responses = getattr(self._provider, method_name)(*args, **kwargs)
        except Exception as error:
            is_current = waiting is None or waiting.current()
            if waiting is not None:
                waiting.cancel()
            if is_current:
                tracker.fail(_model_failure_code(error))
            raise
        return _observe_generator(self._connection, responses, waiting)

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
    backend = _backend(connection)
    if backend == "cosyvoice3":
        # 先把缓冲实现替换为分块实现，再由下面的通用计时器包住最终入口。
        from cosyvoice_streaming import install_cosyvoice_streaming
        install_cosyvoice_streaming(tts, connection)
        # 首段合并短开头，后续保留自然边界；模型与记忆核心不承担切段职责。
        install_cosyvoice_punctuation_policy(tts)
    original_stream = getattr(tts, "to_tts_stream", None)
    original_opus = getattr(tts, "handle_opus", None)
    active_segment = threading.local()
    if callable(original_stream):
        def measured_stream(*args, **kwargs):
            tracker = connection._longmemory_voice_latency
            tracker.bind_sentence()
            sentence_id = getattr(tts, "current_sentence_id", None)
            handle = tracker.begin_tts_segment(sentence_id=sentence_id)
            active_segment.handle = handle
            try:
                return original_stream(*args, **kwargs)
            finally:
                tracker.complete_tts_segment(handle, sentence_id=sentence_id)
                active_segment.handle = None
        tts.to_tts_stream = measured_stream
    if callable(original_opus):
        def measured_opus(*args, **kwargs):
            tracker = connection._longmemory_voice_latency
            tracker.bind_sentence()
            sentence_id = getattr(tts, "current_sentence_id", None)
            tracker.record_tts_audio_packet(
                getattr(active_segment, "handle", None), sentence_id=sentence_id
            )
            tracker.mark("audio_ready_ms", sentence_id=sentence_id)
            waiting = getattr(connection, "_longmemory_waiting", None)
            if waiting is not None and waiting.current() and sentence_id == waiting.sentence_id:
                mark_answer_ready(connection)
                if args and isinstance(args[0], bytes):
                    args = (AnswerPacket(args[0], waiting), *args[1:])
            return original_opus(*args, **kwargs)
        tts.handle_opus = measured_opus
    if backend == "edge":
        install_edge_first_chunk_policy(tts)
    elif backend == "cosyvoice3":
        # 必须最后安装：外层调度每次调用内层单段计时，不能把预取的多段记成一段。
        install_cosyvoice_ready_segment_drain(tts, connection)
    tts._longmemory_latency_observed = True


def install_voice_latency(connection_class):
    """在顶层回答入口建立计时轮次；递归工具调用仍属于同一轮。"""
    if getattr(connection_class, "_longmemory_latency_installed", False):
        return
    original = connection_class.chat

    def chat(connection, query, depth=0):
        if depth == 0:
            old_waiting = getattr(connection, "_longmemory_waiting", None)
            if old_waiting is not None:
                old_waiting.cancel()
                del connection._longmemory_waiting
        if not hasattr(connection, "_longmemory_voice_latency"):
            connection._longmemory_voice_latency = VoiceLatencyTracker(connection)
        tracker = connection._longmemory_voice_latency
        turn_token = tracker.begin() if depth == 0 else None
        _observe_components(connection)
        try:
            return original(connection, query, depth)
        finally:
            if depth == 0:
                tracker.bind_sentence()
                tracker.mark("response_completed_ms", token=turn_token)

    connection_class.chat = chat
    connection_class._longmemory_latency_installed = True


def observed_audio_sender(original):
    """在现有发送协程真正返回后标记首包；空的 FIRST/LAST 控制帧不计。"""
    async def send(connection, sentence_type, audios, text, sentence_id=None):
        first_packet = audios[0] if isinstance(audios, (list, tuple)) and audios else audios
        if isinstance(first_packet, WaitingPacket):
            state = first_packet.state
            if not state.current():
                return
            if not isinstance(first_packet, AnswerPacket) and state.answer_ready and state.first_feedback_ms is None:
                state.cue_state = "skipped"
                return
        result = await original(connection, sentence_type, audios, text, sentence_id)
        has_audio = isinstance(audios, bytes) and bool(audios)
        has_audio = has_audio or (isinstance(audios, (list, tuple)) and len(audios) > 0)
        tracker = getattr(connection, "_longmemory_voice_latency", None)
        is_waiting = isinstance(first_packet, WaitingPacket) and not isinstance(first_packet, AnswerPacket)
        # 实时模式的答案交给最终 socket 包装器计时；这里返回可能只是入流控队列。
        if has_audio and tracker is not None and not is_waiting and not isinstance(first_packet, AnswerPacket):
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
