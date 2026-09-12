"""把固定 Xiaozhi ``CustomTTS`` 实例升级为 CosyVoice 本机分块消费端。

这不是通用互联网流式协议。服务只监听 127.0.0.1，响应由 4 字节大端长度和独立
WAV 块组成。任何协议错误都在尚未播放时回退现有完整 WAV；一旦已经交付音频，
后续错误只停止本段，避免把整句重新播一遍。
"""

import struct

import requests


STREAM_URL = "http://127.0.0.1:18770/v1/audio/stream"
MAX_CHUNK_BYTES = 16 * 1024 * 1024


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
        delivered = False
        try:
            with requests.post(
                STREAM_URL,
                json={"input": cleaned, "response_format": "wav", "stream": True, "cache": False},
                timeout=(3, tts.tts_timeout),
                stream=True,
            ) as response:
                response.raise_for_status()
                expected = "application/vnd.longmemory.wav-chunks"
                if response.headers.get("Content-Type") != expected:
                    raise ValueError("cosyvoice_stream_content_type_invalid")
                for wav in iter_wav_chunks(response.raw):
                    if connection.client_abort or tts.tts_stop_request:
                        return None
                    if not delivered:
                        tts.tts_audio_queue.put((
                            SentenceType.FIRST,
                            None,
                            original_text,
                            getattr(tts, "current_sentence_id", None),
                        ))
                    audio_bytes_to_data_stream(
                        wav,
                        file_type="wav",
                        is_opus=True,
                        callback=opus_handler,
                        sample_rate=connection.sample_rate,
                        opus_encoder=tts.opus_encoder,
                    )
                    delivered = True
                if not delivered:
                    raise ValueError("cosyvoice_stream_empty")
        except Exception as error:
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
