"""把固定 Xiaozhi ``CustomTTS`` 实例升级为 CosyVoice 本机分块消费端。

这不是通用互联网流式协议。服务只监听 127.0.0.1，响应由 4 字节大端长度和独立
WAV 块组成。任何协议错误都在尚未播放时回退现有完整 WAV；一旦已经交付音频，
后续错误只停止本段，避免把整句重新播一遍。
"""

import struct
import http.client
import socket
import threading
import time
from collections import deque
import wave
from contextlib import contextmanager
from math import gcd
from urllib.parse import urlsplit
from io import BytesIO
from pathlib import Path

import requests

from fast_voice_responses import fast_asset_for_text
from cosyvoice_profiles import default_voice_active
from voice_diagnostics import for_sentence
from voice_interruption import OutputLease
from cosyvoice_delivery import configured_mode, session_for


STREAM_URL = "http://127.0.0.1:18770/v1/audio/stream"
MAX_CHUNK_BYTES = 16 * 1024 * 1024
PRESET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/voice-fastpath/cosyvoice3"


class _SpeechCancelled(Exception):
    """内部控制信号：过期片段不能被当成网络故障而重新完整合成。"""


class _ReaderCleanupTimeout(RuntimeError):
    """自有读流尚未结束，不能同时启动完整WAV回退请求。"""


class CosyVoicePacket(bytes):
    """保留编码时的轮次归属，不能在稍后回调中重新读取可变的current_sentence_id。"""

    def __new__(cls, value, sentence_id, cancelled):
        packet = super().__new__(cls, value)
        packet._longmemory_cosy_sentence_id = sentence_id
        packet._longmemory_cosy_cancelled = cancelled
        return packet


def _read_exact(raw, size):
    parts = []
    remaining = size
    while remaining:
        value = raw.read(remaining)
        if not value:
            raise EOFError("cosyvoice_stream_ended")
        parts.append(value)
        remaining -= len(value)
    return b"".join(parts)


def iter_wav_chunks(raw, *, require_end=False):
    """严格解析长度前缀；不相信本机服务返回的块大小。"""
    while True:
        first = raw.read(1)
        if not first:
            if require_end:
                raise EOFError("cosyvoice_stream_missing_end")
            return
        header = first + _read_exact(raw, 3)
        size = struct.unpack("!I", header)[0]
        if size == 0 and require_end:
            return
        if not 0 < size <= MAX_CHUNK_BYTES:
            raise ValueError("cosyvoice_stream_chunk_invalid")
        yield _read_exact(raw, size)


def _wav_chunk_to_pcm(wav: bytes, sample_rate: int) -> bytes:
    """服务契约固定24kHz单声道PCM16；只解包，不逐块重置重采样相位。"""
    with wave.open(BytesIO(wav), "rb") as audio:
        if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                or audio.getframerate() != sample_rate or audio.getcomptype() != "NONE"):
            raise ValueError("cosyvoice_wave_format_changed")
        pcm = audio.readframes(audio.getnframes())
        if not pcm or len(pcm) != audio.getnframes() * 2:
            raise ValueError("cosyvoice_wave_truncated")
        return pcm


class ContinuousPCM:
    """跨原生块保留FIR历史和分数相位，仅在整段真正结束时冲刷尾样本。

    与scipy默认Kaiser多相重采样使用相同滤波器及零相位对齐。固定输入24kHz，
    输出16/24kHz；重采样只增加约1ms滤波器前视，不等待完整标点片段。
    """
    def __init__(self, sample_rate):
        if sample_rate not in (16000, 24000):
            raise ValueError("cosyvoice_output_rate_unsupported")
        self.sample_rate = sample_rate
        divisor = gcd(24000, sample_rate)
        self.up, self.down = sample_rate // divisor, 24000 // divisor
        self.input_samples = self.output_samples = self.grid = 0
        self.finished = False
        if self.up != self.down:
            import numpy as np
            from scipy.signal import firwin
            self.half = 10 * max(self.up, self.down)
            self.taps = firwin(2 * self.half + 1, 1 / max(self.up, self.down),
                              window=("kaiser", 5.0)) * self.up
            self.history = np.zeros(len(self.taps) - 1)

    def _filter(self, values):
        import numpy as np
        from scipy.signal import lfilter
        filtered, self.history = lfilter(self.taps, [1.0], values, zi=self.history)
        positions = np.arange(self.grid, self.grid + len(values))
        selected = filtered[(positions >= self.half) & ((positions - self.half) % self.down == 0)]
        self.grid += len(values)
        self.output_samples += len(selected)
        return np.rint(np.clip(selected, -32768, 32767)).astype("<i2").tobytes()

    def feed(self, wav):
        if self.finished:
            raise ValueError("cosyvoice_pcm_already_finished")
        pcm = _wav_chunk_to_pcm(wav, 24000)
        if len(pcm) % 2:
            raise ValueError("cosyvoice_pcm_unaligned")
        self.input_samples += len(pcm) // 2
        if self.up == self.down:
            self.output_samples += len(pcm) // 2
            return pcm
        import numpy as np
        values = np.zeros(len(pcm) // 2 * self.up)
        values[::self.up] = np.frombuffer(pcm, dtype="<i2")
        return self._filter(values)

    def finish(self):
        if self.finished:
            raise ValueError("cosyvoice_pcm_finished_twice")
        self.finished = True
        if self.up == self.down or not self.input_samples:
            return b""
        import numpy as np
        expected = (self.input_samples * self.up + self.down - 1) // self.down
        last_grid = self.half + (expected - 1) * self.down
        tail = self._filter(np.zeros(max(0, last_grid + 1 - self.grid)))
        if self.output_samples != expected:
            raise ValueError("cosyvoice_resample_length_invalid")
        return tail


@contextmanager
def _open_stream(_url, *, json, timeout, headers, cancelled, **_kwargs):
    """持有自有socket；首次明确busy后最多400ms准入等待，不限制已获200的生成。"""
    import json as json_module
    target = urlsplit(_url)
    if (target.scheme != 'http' or target.hostname != '127.0.0.1' or target.port is None
            or target.path != '/v1/audio/stream' or target.query or target.fragment
            or target.username is not None or target.password is not None):
        raise ValueError('cosyvoice_stream_loopback_required')
    busy_deadline = None  # 首请求保留原超时；只对已确认尚未生成的busy开放重试。
    while True:
        if cancelled():
            raise _SpeechCancelled()
        def remaining(limit):
            if busy_deadline is None:
                return limit
            left = busy_deadline - time.monotonic()
            if left <= 0:
                raise RuntimeError("cosyvoice_stream_http_rejected")
            return min(limit, left)
        connection = http.client.HTTPConnection("127.0.0.1", target.port, timeout=remaining(timeout[0]))
        done = threading.Event()
        admitted = threading.Event()
        watcher = response = None
        retry_busy = False
        try:
            connection.connect()
            owned_socket = connection.sock
            owned_socket.settimeout(remaining(timeout[1]))
            def watch(own_done=done, own_socket=owned_socket, own_admitted=admitted):
                while not own_done.wait(.02):
                    if (cancelled() or (busy_deadline is not None and not own_admitted.is_set()
                                       and time.monotonic() >= busy_deadline)):
                        try:
                            own_socket.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        return
            watcher = threading.Thread(target=watch, name="cosyvoice-http-cancel", daemon=True)
            watcher.start()
            connection.request("POST", "/v1/audio/stream", json_module.dumps(json).encode(),
                               {"Content-Type": "application/json", **headers})
            owned_socket.settimeout(remaining(timeout[1]))
            response = connection.getresponse()
            if cancelled():
                raise _SpeechCancelled()
            if response.status != 200:
                # 固定服务明确busy表示尚未进入合成；只等旧请求finally释放，不重放已开始的生成。
                length = response.headers.get("Content-Length", "")
                if (response.status == 503 and response.headers.get_content_type() == "application/json"
                        and length.isdecimal() and 0 < int(length) <= 128):
                    owned_socket.settimeout(remaining(min(timeout[1], .2)))
                    try:
                        retry_busy = json_module.loads(response.read(int(length))) == {"error": "busy"}
                    except (ValueError, OSError):
                        pass
                if not retry_busy:
                    raise RuntimeError("cosyvoice_stream_http_rejected")
                if busy_deadline is None:
                    busy_deadline = time.monotonic() + .4
                remaining(timeout[1])
            else:
                remaining(timeout[1])
                admitted.set()
                owned_socket.settimeout(timeout[1])
                yield type("StreamResponse", (), {"raw": response, "headers": response.headers,
                            "raise_for_status": lambda self: None})()
                return
        except OSError:
            if cancelled():
                raise _SpeechCancelled() from None
            if busy_deadline is not None and not admitted.is_set():
                # socket定时器可略早于单调时钟deadline返回；仍是失败准入，不重试。
                raise RuntimeError("cosyvoice_stream_http_rejected") from None
            raise
        finally:
            done.set()
            if response is not None:
                response.close()
            connection.close()
            if watcher is not None:
                watcher.join(timeout=.2)
        # 只在无生成的显式busy上等待；每20ms检查本轮永久撤权。
        until = min(busy_deadline, time.monotonic() + .02)
        while time.monotonic() < until:
            if cancelled():
                raise _SpeechCancelled()
            time.sleep(min(.005, max(0, until - time.monotonic())))


def _reset_opus_encoder(opus_encoder) -> None:
    reset = getattr(opus_encoder, "reset_state", None)
    if callable(reset):
        reset()


class PlaybackTimeline:
    """60ms帧的供给时间线；估算欠载，不能当作设备实际扬声器测量。"""

    def __init__(self, *, clock=time.perf_counter):
        self.clock = clock
        self.started = clock()
        self.until = None
        self.first_ms = None
        self.packets = 0
        self.gaps = []

    def packet(self):
        now = self.clock()
        if self.first_ms is None:
            self.first_ms = (now - self.started) * 1000
        if self.until is not None and now > self.until:
            self.gaps.append((now - self.until) * 1000)
        self.until = max(now, self.until or now) + .06
        self.packets += 1

    def ahead_ms(self):
        return max(0, ((self.until or self.clock()) - self.clock()) * 1000)

    def snapshot(self):
        return {
            "measurement": "estimated_opus_supply",
            "first_effective_packet_ms": self.first_ms,
            "playable_ms": self.packets * 60,
            "estimated_end_ms": None if self.until is None else (self.until - self.started) * 1000,
            "max_underflow_ms": max(self.gaps, default=0),
            "total_underflow_ms": sum(self.gaps),
            "underflow_count": len(self.gaps),
        }


class AdaptivePCMBuffer:
    """独立读流、有界PCM预取及欠载恢复；共享Opus编码器始终留在消费线程。

    只在显式adaptive候选使用。producer的取消必须关闭其自有socket；退出前join，
    因而迟到读流线程永远不能重置下一轮的编码器。正常EOF才允许释放不足缓冲的尾段。
    """

    def __init__(self, source, sample_rate, cancelled, timeline, *, initial_ms=360,
                 maximum_ms=3000, clock=time.perf_counter):
        if (type(initial_ms) is not int or not 60 <= initial_ms <= 900
                or type(maximum_ms) is not int or maximum_ms < 960
                or maximum_ms > 6000 or sample_rate not in (16000, 24000)):
            raise ValueError("cosyvoice_buffer_policy_invalid")
        self.source, self.sample_rate = source, sample_rate
        self.cancelled, self.timeline, self.clock = cancelled, timeline, clock
        self.initial_ms, self.target_ms, self.maximum_ms = initial_ms, initial_ms, maximum_ms
        self.frame_bytes = sample_rate * 60 // 1000 * 2
        self.capacity = maximum_ms // 60
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.queue = deque()
        self.done, self.error = False, None
        self.peak_frames = self.rebuffers = self.samples = 0
        self.started = clock()
        self.producer_ms = None
        self.discarded_ms = self.reader_join_ms = 0
        self.thread = None

    def is_cancelled(self):
        return self.stop.is_set() or self.cancelled()

    def _check(self):
        if self.is_cancelled():
            raise _SpeechCancelled()

    def _put(self, pcm):
        with self.condition:
            while len(self.queue) >= self.capacity:
                self._check()
                self.condition.wait(.02)
            self._check()
            self.queue.append(pcm)
            self.samples += len(pcm) // 2
            self.peak_frames = max(self.peak_frames, len(self.queue))
            self.condition.notify_all()

    def _produce(self):
        iterator = None
        try:
            iterator = iter(self.source(self.is_cancelled))
            pending = bytearray()
            for pcm in iterator:
                self._check()
                if len(pcm) % 2:
                    raise ValueError("cosyvoice_pcm_unaligned")
                # 每个槽最多60ms。巨大原生块不把队列容量变成无效的“块数”限制。
                for offset in range(0, len(pcm), self.frame_bytes):
                    pending.extend(pcm[offset:offset + self.frame_bytes])
                    if len(pending) >= self.frame_bytes:
                        self._put(bytes(pending[:self.frame_bytes]))
                        del pending[:self.frame_bytes]
            self._check()
            if pending:
                self._put(bytes(pending))
        except BaseException as error:
            with self.condition:
                self.error = error
        finally:
            try:
                if iterator is not None:
                    close = getattr(iterator, "close", None)
                    if callable(close):
                        close()
            except BaseException as error:
                with self.condition:
                    self.error = self.error or error
            with self.condition:
                self.producer_ms = (self.clock() - self.started) * 1000
                self.done = True
                self.condition.notify_all()

    def __iter__(self):
        if self.thread is not None:
            raise RuntimeError("cosyvoice_buffer_already_consumed")
        self.thread = threading.Thread(target=self._produce, name="cosyvoice-pcm-reader", daemon=True)
        self.thread.start()
        buffering = True
        while True:
            with self.condition:
                self._check()
                # 错误前尚未交付的积压一律丢弃；不能将截断当正常EOF冲刷。
                if self.error is not None:
                    raise self.error
                if self.done and not self.queue:
                    return
                ahead = self.timeline.ahead_ms()
                queued_ms = sum(len(pcm) for pcm in self.queue) / (self.sample_rate * 2) * 1000
                if not buffering and not self.queue and ahead <= 0 and not self.done:
                    buffering = True
                    self.rebuffers += 1
                    self.target_ms = min(900, self.target_ms + 180)
                if (self.queue and ahead + 60 <= self.maximum_ms
                        and (not buffering or self.done or queued_ms + ahead >= self.target_ms)):
                    buffering = False
                    value = self.queue.popleft()
                    self.condition.notify_all()
                else:
                    self.condition.wait(.02)
                    continue
            yield value

    def close(self):
        started = self.clock()
        self.stop.set()
        with self.condition:
            self.discarded_ms += sum(len(pcm) for pcm in self.queue) / (self.sample_rate * 2) * 1000
            self.queue.clear()
            self.condition.notify_all()
        if self.thread is not None:
            # 本机HTTP连接上限3s；读socket由20ms观察线程shutdown。
            self.thread.join(timeout=3.5)
            if self.thread.is_alive():
                raise _ReaderCleanupTimeout("cosyvoice_reader_cleanup_timeout")
        self.reader_join_ms = (self.clock() - started) * 1000

    def snapshot(self):
        duration = self.samples / self.sample_rate * 1000
        return {"initial_buffer_target_ms": self.initial_ms, "rebuffer_target_ms": self.target_ms,
                "peak_buffer_ms": self.peak_frames * 60, "rebuffer_count": self.rebuffers,
                "received_audio_ms": duration, "producer_wall_ms": self.producer_ms,
                "discarded_local_buffer_ms": self.discarded_ms, "reader_join_ms": self.reader_join_ms,
                # 含HTTP/重采样/背压等待；不是模型纯推理RTF。
                "client_receive_rtf": None if not duration or self.producer_ms is None
                    else self.producer_ms / duration,
                "reader_stopped": self.thread is None or not self.thread.is_alive()}


def install_cosyvoice_streaming(tts, connection):
    """仅改写当前连接的 CosyVoice 实例，其他 TTS 和第三方源码保持不变。"""
    if getattr(tts, "_longmemory_cosy_streaming_installed", False):
        return
    original = getattr(tts, "to_tts_stream", None)
    if not callable(original):
        return

    from core.providers.tts.dto.dto import SentenceType
    from core.utils.tts import MarkdownCleaner
    from core.utils.util import audio_bytes_to_data_stream

    encoder_lock = threading.Lock()

    def stream(text, opus_handler, sentence_id, lease):
        original_text = text
        trace = for_sentence(connection, sentence_id)

        def cancelled():
            # 新 chat 会重新清空 client_abort；捕获的旧话轮身份仍必须永久失效。
            current = getattr(connection, "sentence_id", sentence_id)
            return (
                not lease.current() or connection.client_abort or tts.tts_stop_request
                or (getattr(connection, 'stop_event', None) is not None
                    and connection.stop_event.is_set())
                or (sentence_id is not None and current != sentence_id)
                or (sentence_id is not None
                    and getattr(tts, "current_sentence_id", sentence_id) != sentence_id)
            )

        def check_current():
            if cancelled():
                raise _SpeechCancelled()

        cleaned = MarkdownCleaner.clean_markdown(text)
        pattern = getattr(tts, "_correct_words_pattern", None)
        if pattern:
            cleaned = pattern.sub(lambda match: tts.correct_words[match.group(0)], cleaned)
        # 表情或词替换可能留下空片段；它不需要合成，也不是流式交付失败。
        # 在创建交付状态和发 HTTP 前跳过，让同一连接的后续正文继续增量。
        if not cleaned.strip():
            return None
        preset_name = fast_asset_for_text(cleaned) if default_voice_active() else None
        preset = PRESET_ROOT / preset_name if preset_name else None
        delivered = False
        handoff_started = False
        # 实测未分段长文存在欠载，自然段也有非零最大缺口，不能按字数推定安全。
        # 日用保持完整片段；只有隔离验收显式设置连接属性才启用增量候选。
        # 此开关不改变声线、语速、权重或60ms帧，也不由标点/字符数暗中打开。
        delivery = session_for(connection)
        mode = delivery.select(configured_mode(connection))
        if mode is None:
            delivery.note("blocked")
            if trace is not None:
                trace.event("tts_failed")
            # 未清理的旧读流或中途改模式，不能再发新请求；上游仍可处理LAST/收音。
            connection.logger.bind(tag="cosyvoice-stream").warning("音频交付需要重连，当前片段未发起合成")
            return None
        pcm_parts = []
        buffer = None
        timeline = None
        if mode == "adaptive":
            previous = getattr(tts, "_longmemory_cosy_playout", None)
            lease_key = (sentence_id, lease.epoch)
            if previous is None or previous[0] != lease_key:
                previous = (lease_key, PlaybackTimeline())
                tts._longmemory_cosy_playout = previous
            timeline = previous[1]
        outcome = "failed"
        reader_cleanup = "not_required"

        def deliver_opus(packet):
            """直到拿到完整 Opus 帧才宣布开始，避免空模型块造成假首包。"""
            nonlocal delivered, handoff_started
            check_current()
            if not delivered:
                tts.tts_audio_queue.put((
                    SentenceType.FIRST,
                    None,
                    original_text,
                    sentence_id,
                ))
            tagged = CosyVoicePacket(packet, sentence_id, cancelled)
            tagged._longmemory_output_lease = lease
            # 回调可能已入队/写出后才抛错；不确定时也不能把整段回退重播。
            if not handoff_started:
                delivery.mark_handoff()
                handoff_started = True
            opus_handler(tagged)
            if not delivered and lease.current():
                lease.state.note("first_segment_callback_returned")
            delivered = True
            if timeline is not None:
                timeline.packet()

        def source(is_cancelled):
            with _open_stream(
                STREAM_URL,
                json={"input": cleaned, "response_format": "wav", "stream": True,
                      "cache": getattr(connection, '_longmemory_cosy_reply_cache', True),
                      "delivery_mode": "incremental" if mode == "adaptive" else mode},
                timeout=(3, tts.tts_timeout), stream=True,
                headers=trace.headers() if trace is not None else {}, cancelled=is_cancelled,
            ) as response:
                if trace is not None:
                    trace.event("tts_response", request_id=response.headers.get("X-Request-Id"))
                response.raise_for_status()
                if response.headers.get("Content-Type") != "application/vnd.longmemory.wav-chunks":
                    raise ValueError("cosyvoice_stream_content_type_invalid")
                if response.headers.get("X-LongMemory-Audio-Stream") != "2":
                    raise ValueError("cosyvoice_incremental_contract_missing")
                with lease.state.lock:
                    if lease.current() and lease.state.observed is not None:
                        lease.state.observed["v2_transport_confirmed"] = True
                decoder = ContinuousPCM(connection.sample_rate)
                for wav in iter_wav_chunks(response.raw, require_end=True):
                    if is_cancelled():
                        raise _SpeechCancelled()
                    pcm = decoder.feed(wav)
                    if is_cancelled():
                        raise _SpeechCancelled()
                    if pcm:
                        yield pcm
                if is_cancelled():
                    raise _SpeechCancelled()
                # 仅正常结束冲刷FIR尾；取消或截断永远不制造完整段尾。
                tail = decoder.finish()
                if tail:
                    yield tail

        delivery.begin()
        try:
            check_current()
            if preset is not None and preset.is_file():
                lease.state.producer("preset", lease=lease)
                audio_bytes_to_data_stream(
                    preset.read_bytes(), file_type="wav", is_opus=True,
                    callback=deliver_opus, sample_rate=connection.sample_rate,
                    opus_encoder=tts.opus_encoder,
                )
                outcome = "preset"
                return None
            if mode == "adaptive":
                lease.state.producer("adaptive_buffer", "incremental", lease=lease)
                buffer = AdaptivePCMBuffer(source, connection.sample_rate, cancelled, timeline)
                pieces = iter(buffer)
            else:
                lease.state.producer(mode + "_pcm", mode, lease=lease)
                pieces = source(cancelled)
            try:
                reader_cleanup = "unconfirmed"
                delivery.reader_started()
                for pcm in pieces:
                    check_current()
                    if mode == "buffered":
                        pcm_parts.append(pcm)
                    else:
                        tts.opus_encoder.encode_pcm_to_opus_stream(
                            pcm, end_of_stream=False, callback=deliver_opus)
                check_current()
                tts.opus_encoder.encode_pcm_to_opus_stream(
                    b"".join(pcm_parts), end_of_stream=True, callback=deliver_opus
                )
                if not delivered:
                    raise ValueError("cosyvoice_stream_empty")
                outcome = "completed"
            finally:
                try:
                    pieces.close()
                finally:
                    if buffer is not None:
                        buffer.close()
                reader_cleanup = "confirmed"
        except _SpeechCancelled:
            outcome = "failed" if reader_cleanup == "unconfirmed" else "cancelled"
            if reader_cleanup == "unconfirmed":
                delivery.degrade("reader_cleanup_unconfirmed", blocked=True)
            if trace is not None:
                trace.event("tts_cancelled")
            _reset_opus_encoder(tts.opus_encoder)
            return None
        except _ReaderCleanupTimeout:
            outcome = "failed"
            delivery.degrade("reader_cleanup_timeout", blocked=True)
            _reset_opus_encoder(tts.opus_encoder)
            connection.logger.bind(tag="cosyvoice-stream").warning("读流清理超时，本段停止且不并发回退")
            return None
        except Exception as error:
            outcome = "failed"
            if trace is not None:
                trace.event("tts_timeout" if isinstance(error, (requests.Timeout, TimeoutError)) else "tts_failed")
            # 解码、协议或发送失败时清除残留 PCM，避免污染回退或下一句话。
            _reset_opus_encoder(tts.opus_encoder)
            if reader_cleanup == "unconfirmed":
                delivery.degrade("reader_cleanup_unconfirmed", blocked=True)
                connection.logger.bind(tag="cosyvoice-stream").warning("读流清理未确认，本段停止且不追加合成")
                return None
            if cancelled():
                outcome = "cancelled"
                return None
            delivery.degrade("after_handoff" if handoff_started else "before_handoff")
            if not handoff_started:
                if trace is not None:
                    trace.event("tts_fallback")
                connection.logger.bind(tag="cosyvoice-stream").warning(
                    f"分块通道在首个音频前失败，回退完整 WAV：{type(error).__name__}"
                )
                fallback_delivery_failed = False
                def fallback_packet(packet):
                    nonlocal handoff_started, fallback_delivery_failed
                    # 完整 WAV 请求期间也可能开始新话轮。这里丢弃而不抛取消信号，
                    # 否则上游兼容方法可能把正常打断当成合成失败并重试多次。
                    if not cancelled() and not fallback_delivery_failed:
                        tagged = CosyVoicePacket(packet, sentence_id, cancelled)
                        tagged._longmemory_output_lease = lease
                        if not handoff_started:
                            delivery.mark_handoff()
                            handoff_started = True
                        try:
                            opus_handler(tagged)
                        except Exception:
                            # 固定上游把回调异常也当成可重试合成；交付可能开始后
                            # 必须吞掉该重试信号、丢弃尾回调，再由本层记录失败。
                            fallback_delivery_failed = True

                try:
                    outcome = "fallback"
                    try:
                        lease.state.producer("complete_wav_fallback", "full_wav", lease=lease)
                        result = original(text, opus_handler=fallback_packet)
                    except Exception:
                        outcome = "failed"
                        if handoff_started:
                            delivery.degrade("after_handoff")
                        raise
                    if cancelled():
                        outcome = "cancelled"
                    elif fallback_delivery_failed:
                        outcome = "failed"
                        delivery.degrade("after_handoff")
                        _reset_opus_encoder(tts.opus_encoder)
                        connection.logger.bind(tag="cosyvoice-stream").warning("完整音频回退交付失败，未重播本段")
                    elif not handoff_started:
                        # 固定上游耗尽生成/解码重试也会直接返回None；没有任何
                        # 音频回调就不能把方法返回记成回退成功。
                        outcome = "failed"
                        delivery.degrade("before_handoff")
                        _reset_opus_encoder(tts.opus_encoder)
                        connection.logger.bind(tag="cosyvoice-stream").warning("完整音频回退未交付音频")
                    return result
                finally:
                    if cancelled():
                        _reset_opus_encoder(tts.opus_encoder)
            connection.logger.bind(tag="cosyvoice-stream").warning(
                f"分块通道在播放后中止：{type(error).__name__}"
            )
        finally:
            delivery.note(outcome, handoff=handoff_started, cleanup=reader_cleanup)
            if buffer is not None:
                report = {**buffer.snapshot(), **timeline.snapshot(), "outcome": outcome}
                tracker = getattr(connection, "_longmemory_voice_latency", None)
                record = getattr(tracker, "record_continuity", None)
                if callable(record):
                    record(report, sentence_id=sentence_id)
        return None

    def serialized_stream(text, opus_handler=None):
        # 捕获排队前身份；旧调用的finally/reset不得清空新轮编码器或吞掉新轮音频。
        sentence_id = getattr(tts, "current_sentence_id", None)
        lease = OutputLease(connection, sentence_id, producing=True)
        acquired = False
        try:
            while not encoder_lock.acquire(timeout=.02):
                if (not lease.current() or sentence_id != getattr(tts, "current_sentence_id", None)
                        or connection.client_abort or tts.tts_stop_request):
                    return None
            acquired = True
            if not lease.current() or sentence_id != getattr(tts, "current_sentence_id", None):
                return None
            return stream(text, opus_handler, sentence_id, lease)
        finally:
            if acquired:
                encoder_lock.release()
            lease.release()

    tts.to_tts_stream = serialized_stream
    tts._longmemory_cosy_streaming_installed = True
