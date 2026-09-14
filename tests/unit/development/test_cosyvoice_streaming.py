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
