"""把固定 Xiaozhi ``CustomTTS`` 实例升级为 CosyVoice 本机分块消费端。

这不是通用互联网流式协议。服务只监听 127.0.0.1，响应由 4 字节大端长度和独立
WAV 块组成。任何协议错误都在尚未播放时回退现有完整 WAV；一旦已经交付音频，
后续错误只停止本段，避免把整句重新播一遍。
"""

import struct
from io import BytesIO
from pathlib import Path

import requests

from fast_voice_responses import fast_asset_for_text


STREAM_URL = "http://127.0.0.1:18770/v1/audio/stream"
MAX_CHUNK_BYTES = 16 * 1024 * 1024
PRESET_ROOT = Path(__file__).resolve().parents[3] / "assets/audio/voice-fastpath/cosyvoice3"


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


def iter_wav_chunks(raw):
    """严格解析长度前缀；不相信本机服务返回的块大小。"""
    while True:
        first = raw.read(1)
        if not first:
            return
        header = first + _read_exact(raw, 3)
        size = struct.unpack("!I", header)[0]
        if not 0 < size <= MAX_CHUNK_BYTES:
            raise ValueError("cosyvoice_stream_chunk_invalid")
        yield _read_exact(raw, size)


def _wav_chunk_to_pcm(wav: bytes, sample_rate: int) -> bytes:
    """把模型的独立 WAV 块统一为可连续拼接的单声道 PCM16。"""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(BytesIO(wav), format="wav", parameters=["-nostdin"])
    audio = audio.set_channels(1).set_frame_rate(sample_rate).set_sample_width(2)
    return audio.raw_data


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
        cleaned = MarkdownCleaner.clean_markdown(text)
        pattern = getattr(tts, "_correct_words_pattern", None)
        if pattern:
            cleaned = pattern.sub(lambda match: tts.correct_words[match.group(0)], cleaned)
        preset_name = fast_asset_for_text(cleaned)
        preset = PRESET_ROOT / preset_name if preset_name else None
        if preset is not None and preset.is_file():
            tts.tts_audio_queue.put((
                SentenceType.FIRST,
                None,
                original_text,
                getattr(tts, "current_sentence_id", None),
            ))
            audio_bytes_to_data_stream(
                preset.read_bytes(),
                file_type="wav",
                is_opus=True,
                callback=opus_handler,
                sample_rate=connection.sample_rate,
                opus_encoder=tts.opus_encoder,
            )
            return None
        delivered = False
        pcm_parts = []

        def deliver_opus(packet):
            """直到拿到完整 Opus 帧才宣布开始，避免空模型块造成假首包。"""
            nonlocal delivered
            if not delivered:
                tts.tts_audio_queue.put((
                    SentenceType.FIRST,
                    None,
                    original_text,
                    getattr(tts, "current_sentence_id", None),
                ))
            opus_handler(packet)
            delivered = True

        try:
            with requests.post(
                STREAM_URL,
                json={"input": cleaned, "response_format": "wav", "stream": True, "cache": True},
                timeout=(3, tts.tts_timeout),
                stream=True,
            ) as response:
                response.raise_for_status()
                expected = "application/vnd.longmemory.wav-chunks"
                if response.headers.get("Content-Type") != expected:
                    raise ValueError("cosyvoice_stream_content_type_invalid")
                for wav in iter_wav_chunks(response.raw):
                    if connection.client_abort or tts.tts_stop_request:
                        # 未满一帧的 PCM 属于已取消话轮，不能混入下一次合成。
                        _reset_opus_encoder(tts.opus_encoder)
                        return None
                    pcm_parts.append(_wav_chunk_to_pcm(wav, connection.sample_rate))
                # 当前 PyTorch 后端的模型块供给慢于播放。一个标点片段完整生成后再
                # 连续编码，停顿只可能出现在文本切段边界，不会落在词语中间。
                tts.opus_encoder.encode_pcm_to_opus_stream(
                    b"".join(pcm_parts), end_of_stream=True, callback=deliver_opus
                )
                if not delivered:
                    raise ValueError("cosyvoice_stream_empty")
        except Exception as error:
            # 解码、协议或发送失败时清除残留 PCM，避免污染回退或下一句话。
            _reset_opus_encoder(tts.opus_encoder)
            if not delivered:
                connection.logger.bind(tag="cosyvoice-stream").warning(
                    f"分块通道在首个音频前失败，回退完整 WAV：{type(error).__name__}"
                )
                return original(text, opus_handler=opus_handler)
            connection.logger.bind(tag="cosyvoice-stream").warning(
                f"分块通道在播放后中止：{type(error).__name__}"
            )
        return None

    tts.to_tts_stream = stream
    tts._longmemory_cosy_streaming_installed = True
