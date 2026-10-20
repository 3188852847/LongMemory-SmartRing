"""把固定 Xiaozhi ``CustomTTS`` 实例升级为 CosyVoice 本机分块消费端。

这不是通用互联网流式协议。服务只监听 127.0.0.1，响应由 4 字节大端长度和独立
WAV 块组成。任何协议错误都在尚未播放时回退现有完整 WAV；一旦已经交付音频，
后续错误只停止本段，避免把整句重新播一遍。
"""

import struct
import http.client
import socket
import threading
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


STREAM_URL = "http://127.0.0.1:18770/v1/audio/stream"
MAX_CHUNK_BYTES = 16 * 1024 * 1024
PRESET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/voice-fastpath/cosyvoice3"


class _SpeechCancelled(Exception):
    """内部控制信号：过期片段不能被当成网络故障而重新完整合成。"""


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
    """持有自己创建的socket，取消可打断阻塞读取；不追随重定向或环境代理。"""
    import json as json_module
    target = urlsplit(_url)
    if (target.scheme != 'http' or target.hostname != '127.0.0.1' or target.port is None
            or target.path != '/v1/audio/stream' or target.query or target.fragment
            or target.username is not None or target.password is not None):
        raise ValueError('cosyvoice_stream_loopback_required')
    connection = http.client.HTTPConnection("127.0.0.1", target.port, timeout=timeout[0])
    done = threading.Event()
    watcher = None
    response = None
    try:
        connection.connect()
        owned_socket = connection.sock
        owned_socket.settimeout(timeout[1])
        def watch():
            while not done.wait(.02):
                if cancelled():
                    try:
                        owned_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
        watcher = threading.Thread(target=watch, name="cosyvoice-http-cancel", daemon=True)
        watcher.start()
        connection.request("POST", "/v1/audio/stream", json_module.dumps(json).encode(),
                           {"Content-Type": "application/json", **headers})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError("cosyvoice_stream_http_rejected")
        yield type("StreamResponse", (), {"raw": response, "headers": response.headers,
                    "raise_for_status": lambda self: None})()
    finally:
        done.set()
        if response is not None:
            response.close()
        connection.close()
        if watcher is not None:
            watcher.join(timeout=.2)


def _reset_opus_encoder(opus_encoder) -> None:
    reset = getattr(opus_encoder, "reset_state", None)
    if callable(reset):
        reset()


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

    def stream(text, opus_handler=None):
        original_text = text
        sentence_id = getattr(tts, "current_sentence_id", None)
        trace = for_sentence(connection, sentence_id)

        def cancelled():
            # 新 chat 会重新清空 client_abort；捕获的旧话轮身份仍必须永久失效。
            current = getattr(connection, "sentence_id", sentence_id)
            return (
                connection.client_abort or tts.tts_stop_request
                or (getattr(connection, 'stop_event', None) is not None
                    and connection.stop_event.is_set())
                or (sentence_id is not None and current != sentence_id)
            )

        def check_current():
            if cancelled():
                raise _SpeechCancelled()

        cleaned = MarkdownCleaner.clean_markdown(text)
        pattern = getattr(tts, "_correct_words_pattern", None)
        if pattern:
            cleaned = pattern.sub(lambda match: tts.correct_words[match.group(0)], cleaned)
        preset_name = fast_asset_for_text(cleaned) if default_voice_active() else None
        preset = PRESET_ROOT / preset_name if preset_name else None
        delivered = False
        # 回退开关只改变交付策略；不会换声线、语速、权重或60ms帧。
        mode = getattr(connection, "_longmemory_cosy_delivery_mode", "incremental")
        if mode not in {"incremental", "buffered"}:
            raise ValueError("cosyvoice_delivery_mode_invalid")
        pcm_parts = []

        def deliver_opus(packet):
            """直到拿到完整 Opus 帧才宣布开始，避免空模型块造成假首包。"""
            nonlocal delivered
            check_current()
            if not delivered:
                tts.tts_audio_queue.put((
                    SentenceType.FIRST,
                    None,
                    original_text,
                    sentence_id,
                ))
            opus_handler(packet)
            delivered = True

        try:
            check_current()
            if preset is not None and preset.is_file():
                audio_bytes_to_data_stream(
                    preset.read_bytes(), file_type="wav", is_opus=True,
                    callback=deliver_opus, sample_rate=connection.sample_rate,
                    opus_encoder=tts.opus_encoder,
                )
                return None
            with _open_stream(
                STREAM_URL,
                json={"input": cleaned, "response_format": "wav", "stream": True,
                      "cache": getattr(connection, '_longmemory_cosy_reply_cache', True),
                      "delivery_mode": mode},
                timeout=(3, tts.tts_timeout),
                stream=True,
                headers=trace.headers() if trace is not None else {},
                cancelled=cancelled,
            ) as response:
                if trace is not None:
                    trace.event("tts_response", request_id=response.headers.get("X-Request-Id"))
                response.raise_for_status()
                expected = "application/vnd.longmemory.wav-chunks"
                if response.headers.get("Content-Type") != expected:
                    raise ValueError("cosyvoice_stream_content_type_invalid")
                if response.headers.get("X-LongMemory-Audio-Stream") != "2":
                    raise ValueError("cosyvoice_incremental_contract_missing")
                decoder = ContinuousPCM(connection.sample_rate)
                for wav in iter_wav_chunks(response.raw, require_end=True):
                    check_current()
                    pcm = decoder.feed(wav)
                    check_current()
                    if mode == "buffered":
                        pcm_parts.append(pcm)
                    elif pcm:
                        tts.opus_encoder.encode_pcm_to_opus_stream(
                            pcm, end_of_stream=False, callback=deliver_opus)
                check_current()
                tail = decoder.finish()
                # 仅协议正常结束才补FIR尾与最后不足60ms帧。截断/取消不补假尾音。
                tts.opus_encoder.encode_pcm_to_opus_stream(
                    b"".join(pcm_parts) + tail, end_of_stream=True, callback=deliver_opus
                )
                if not delivered:
                    raise ValueError("cosyvoice_stream_empty")
        except _SpeechCancelled:
            if trace is not None:
                trace.event("tts_cancelled")
            _reset_opus_encoder(tts.opus_encoder)
            return None
        except Exception as error:
            if trace is not None:
                trace.event("tts_timeout" if isinstance(error, (requests.Timeout, TimeoutError)) else "tts_failed")
            # 解码、协议或发送失败时清除残留 PCM，避免污染回退或下一句话。
            _reset_opus_encoder(tts.opus_encoder)
            if cancelled():
                return None
            if not delivered:
                if trace is not None:
                    trace.event("tts_fallback")
                connection.logger.bind(tag="cosyvoice-stream").warning(
                    f"分块通道在首个音频前失败，回退完整 WAV：{type(error).__name__}"
                )
                def fallback_packet(packet):
                    # 完整 WAV 请求期间也可能开始新话轮。这里丢弃而不抛取消信号，
                    # 否则上游兼容方法可能把正常打断当成合成失败并重试多次。
                    if not cancelled():
                        opus_handler(packet)

                try:
                    return original(text, opus_handler=fallback_packet)
                finally:
                    if cancelled():
                        _reset_opus_encoder(tts.opus_encoder)
            connection.logger.bind(tag="cosyvoice-stream").warning(
                f"分块通道在播放后中止：{type(error).__name__}"
            )
        return None

    tts.to_tts_stream = stream
    tts._longmemory_cosy_streaming_installed = True
