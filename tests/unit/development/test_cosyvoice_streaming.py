"""验证本机分块协议解析；不加载 CosyVoice、CUDA 或 Xiaozhi。"""

from io import BytesIO
import importlib.util
from pathlib import Path
import struct
import sys
import types
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/cosyvoice_streaming.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("cosyvoice_streaming_test", SCRIPT)
streaming = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(streaming)


def framed(*chunks):
    return b"".join(struct.pack("!I", len(chunk)) + chunk for chunk in chunks)


def test_iter_wav_chunks_preserves_boundaries():
    assert list(streaming.iter_wav_chunks(BytesIO(framed(b"first", b"second")))) == [
        b"first", b"second",
    ]


@pytest.mark.parametrize("body", [
    b"\x00\x00", struct.pack("!I", 0), struct.pack("!I", streaming.MAX_CHUNK_BYTES + 1),
    struct.pack("!I", 5) + b"no",
])
def test_iter_wav_chunks_rejects_truncated_or_unbounded_frames(body):
    with pytest.raises((EOFError, ValueError)):
        list(streaming.iter_wav_chunks(BytesIO(body)))


def test_preset_audio_bypasses_http_and_reuses_opus_pipeline(tmp_path, monkeypatch):
    dto = types.ModuleType("core.providers.tts.dto.dto")
    dto.SentenceType = SimpleNamespace(FIRST="first")
    cleaner = types.ModuleType("core.utils.tts")
    cleaner.MarkdownCleaner = SimpleNamespace(clean_markdown=lambda text: text)
    delivered = []
    util = types.ModuleType("core.utils.util")
    util.audio_bytes_to_data_stream = lambda audio, **kwargs: delivered.append((audio, kwargs))
    for name in ("core", "core.providers", "core.providers.tts", "core.providers.tts.dto", "core.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    monkeypatch.setitem(sys.modules, "core.utils.tts", cleaner)
    monkeypatch.setitem(sys.modules, "core.utils.util", util)
    monkeypatch.setattr(streaming, "PRESET_ROOT", tmp_path)
    (tmp_path / "hello.wav").write_bytes(b"synthetic-wave")
    monkeypatch.setattr(
        streaming.requests, "post",
        lambda *_args, **_kwargs: pytest.fail("preset must not call HTTP"),
    )

    queued = []
    tts = SimpleNamespace(
        to_tts_stream=lambda *_args, **_kwargs: pytest.fail("preset must not use fallback"),
        tts_audio_queue=SimpleNamespace(put=queued.append),
        current_sentence_id="turn-1", _correct_words_pattern=None,
        opus_encoder=object(), tts_timeout=90,
    )
    connection = SimpleNamespace(sample_rate=16000, client_abort=False)
    streaming.install_cosyvoice_streaming(tts, connection)
    tts.to_tts_stream("你好呀，我在呢。", opus_handler="callback")

    assert queued == [("first", None, "你好呀，我在呢。", "turn-1")]
    assert delivered[0][0] == b"synthetic-wave"
    assert delivered[0][1]["callback"] == "callback"


def test_stream_keeps_partial_pcm_across_model_chunks_and_flushes_once(monkeypatch):
    dto = types.ModuleType("core.providers.tts.dto.dto")
    dto.SentenceType = SimpleNamespace(FIRST="first")
    cleaner = types.ModuleType("core.utils.tts")
    cleaner.MarkdownCleaner = SimpleNamespace(clean_markdown=lambda text: text)
    util = types.ModuleType("core.utils.util")
    util.audio_bytes_to_data_stream = lambda *_args, **_kwargs: None
    for name in ("core", "core.providers", "core.providers.tts", "core.providers.tts.dto", "core.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    monkeypatch.setitem(sys.modules, "core.utils.tts", cleaner)
    monkeypatch.setitem(sys.modules, "core.utils.util", util)
    decode_count = 0

    def decode(wav, _rate):
        nonlocal decode_count
        decode_count += 1
        # 第一块解码完成时仍不得播放；必须等同一标点片段全部准备好。
        if decode_count == 2:
            assert packets == []
        return wav

    monkeypatch.setattr(streaming, "_wav_chunk_to_pcm", decode)
    monkeypatch.setattr(streaming, "fast_asset_for_text", lambda _text: None)

    class Response:
        headers = {"Content-Type": "application/vnd.longmemory.wav-chunks"}

        def __init__(self):
            self.raw = BytesIO(framed(b"aaaa", b"bbbb"))

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def raise_for_status(self): return None

    monkeypatch.setattr(streaming.requests, "post", lambda *_args, **_kwargs: Response())

    class Encoder:
        def __init__(self):
            self.buffer = bytearray()

        def encode_pcm_to_opus_stream(self, pcm, end_of_stream, callback):
            self.buffer.extend(pcm)
            while len(self.buffer) >= 6:
                callback(bytes(self.buffer[:6]))
                del self.buffer[:6]
            if end_of_stream and self.buffer:
                callback(bytes(self.buffer) + b"\x00" * (6 - len(self.buffer)))
                self.buffer.clear()

        def reset_state(self):
            self.buffer.clear()

    queued = []
    packets = []
    tts = SimpleNamespace(
        to_tts_stream=lambda *_args, **_kwargs: pytest.fail("stream must not fall back"),
        tts_audio_queue=SimpleNamespace(put=queued.append),
        current_sentence_id="turn-2", _correct_words_pattern=None,
        opus_encoder=Encoder(), tts_timeout=90, tts_stop_request=False,
    )
    connection = SimpleNamespace(sample_rate=16000, client_abort=False)
    streaming.install_cosyvoice_streaming(tts, connection)
    tts.to_tts_stream("连续分块", opus_handler=packets.append)

    assert queued == [("first", None, "连续分块", "turn-2")]
    assert packets == [b"aaaabb", b"bb\x00\x00\x00\x00"]
