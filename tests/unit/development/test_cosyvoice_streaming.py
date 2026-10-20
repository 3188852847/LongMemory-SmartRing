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


@pytest.mark.parametrize("text,filename", [
    ("你好呀，我在呢。", "hello.wav"),
    ("我在，听得到。", "present.wav"),
    ("不用客气。", "thanks.wav"),
    ("晚安，做个好梦。", "goodnight.wav"),
])
def test_preset_audio_bypasses_http_and_reuses_opus_pipeline(tmp_path, monkeypatch, text, filename):
    from cosyvoice_segments import install_cosyvoice_punctuation_policy, install_cosyvoice_ready_segment_drain
    dto = types.ModuleType("core.providers.tts.dto.dto")
    dto.SentenceType = SimpleNamespace(FIRST="first")
    cleaner = types.ModuleType("core.utils.tts")
    cleaner.MarkdownCleaner = SimpleNamespace(clean_markdown=lambda text: text)
    delivered = []
    util = types.ModuleType("core.utils.util")
    def encode_preset(audio, **kwargs):
        delivered.append((audio, kwargs))
        kwargs["callback"](b"preset-opus")
    util.audio_bytes_to_data_stream = encode_preset
    for name in ("core", "core.providers", "core.providers.tts", "core.providers.tts.dto", "core.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    monkeypatch.setitem(sys.modules, "core.utils.tts", cleaner)
    monkeypatch.setitem(sys.modules, "core.utils.util", util)
    monkeypatch.setattr(streaming, "PRESET_ROOT", tmp_path)
    (tmp_path / filename).write_bytes(b"synthetic-wave")
    monkeypatch.setattr(
        streaming, "_open_stream",
        lambda *_args, **_kwargs: pytest.fail("preset must not call HTTP"),
    )

    queued = []
    tts = SimpleNamespace(
        to_tts_stream=lambda *_args, **_kwargs: pytest.fail("preset must not use fallback"),
        tts_audio_queue=SimpleNamespace(put=queued.append),
        current_sentence_id="turn-1", _correct_words_pattern=None,
        opus_encoder=object(), tts_timeout=90, tts_stop_request=False,
        tts_text_buff=[], processed_chars=0, is_first_sentence=True,
        _get_segment_text=lambda: pytest.fail("must not use upstream rfind"),
        _process_remaining_text_stream=lambda **_kwargs: pytest.fail("must preserve complete preset"),
    )
    connection = SimpleNamespace(sample_rate=16000, client_abort=False, sentence_id="turn-1")
    streaming.install_cosyvoice_streaming(tts, connection)
    install_cosyvoice_punctuation_policy(tts)
    install_cosyvoice_ready_segment_drain(tts, connection)
    packets = []
    # 经过真实切段入口；旧首逗号策略会拆坏 hello/present/goodnight 的完整命中键。
    for char in text:
        tts.tts_text_buff.append(char)
        segment = tts._get_segment_text()
        if segment:
            tts.to_tts_stream(segment, opus_handler=packets.append)
    assert tts._process_remaining_text_stream(opus_handler=packets.append)
    assert not tts._process_remaining_text_stream(opus_handler=packets.append)

    assert queued == [("first", None, text, "turn-1")]
    assert len(delivered) == 1
    assert delivered[0][0] == b"synthetic-wave"
    assert packets == [b"preset-opus"]


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
        # 首个可播放帧必须在读取第二个模型块之前交付，不再收齐片段。
        if decode_count == 2:
            assert packets == [b"aaaaaa"]
        return wav

    monkeypatch.setattr(streaming, "_wav_chunk_to_pcm", decode)
    monkeypatch.setattr(streaming, "fast_asset_for_text", lambda _text: None)

    class Response:
        headers = {"Content-Type": "application/vnd.longmemory.wav-chunks", "X-LongMemory-Audio-Stream": "2"}

        def __init__(self):
            self.raw = BytesIO(framed(b"aaaaaa", b"bbbb") + struct.pack("!I", 0))

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def raise_for_status(self): return None

    monkeypatch.setattr(streaming, "_open_stream", lambda *_args, **_kwargs: Response())

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
    connection = SimpleNamespace(sample_rate=24000, client_abort=False)
    streaming.install_cosyvoice_streaming(tts, connection)
    tts.to_tts_stream("连续分块", opus_handler=packets.append)

    assert queued == [("first", None, "连续分块", "turn-2")]
    assert packets == [b"aaaaaa", b"bbbb\x00\x00"]


@pytest.fixture
def cancellable_stream(monkeypatch):
    """模拟在读块、解码和编码过程中开始新话轮，不加载真实网络或编码库。"""
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
    monkeypatch.setattr(streaming, "fast_asset_for_text", lambda _text: None)
    monkeypatch.setattr(streaming, "_wav_chunk_to_pcm", lambda wav, _rate: wav)
    state = SimpleNamespace(packets=[], queued=[], requests=0, resets=0, closed=False)
    state.fallback = lambda *_args, **_kwargs: pytest.fail("cancel must not resynthesize")

    class Response:
        headers = {"Content-Type": "application/vnd.longmemory.wav-chunks", "X-LongMemory-Audio-Stream": "2"}

        def __init__(self):
            self.raw = BytesIO(framed(b"abcdef") + struct.pack("!I", 0))

        def __enter__(self): return self
        def __exit__(self, *_args): state.closed = True
        def raise_for_status(self): return None

    def post(*_args, **_kwargs):
        state.requests += 1
        return Response()

    class Encoder:
        def encode_pcm_to_opus_stream(self, _pcm, *, end_of_stream, callback):
            assert end_of_stream is False
            callback(b"first")
            callback(b"second")

        def reset_state(self): state.resets += 1

    monkeypatch.setattr(streaming, "_open_stream", post)
    state.connection = SimpleNamespace(sample_rate=24000, client_abort=False, sentence_id="old")
    state.tts = SimpleNamespace(
        to_tts_stream=lambda *args, **kwargs: state.fallback(*args, **kwargs),
        tts_audio_queue=SimpleNamespace(put=state.queued.append),
        current_sentence_id="old", _correct_words_pattern=None,
        opus_encoder=Encoder(), tts_timeout=90, tts_stop_request=False,
    )
    streaming.install_cosyvoice_streaming(state.tts, state.connection)
    return state


def test_stale_turn_is_rejected_before_http_even_when_abort_was_reset(cancellable_stream):
    state = cancellable_stream
    state.connection.sentence_id = "new"
    state.tts.to_tts_stream("旧片段", opus_handler=state.packets.append)
    assert state.requests == 0
    assert state.packets == state.queued == []
    assert state.resets == 1


def test_abort_during_wav_decode_never_starts_playback(cancellable_stream, monkeypatch):
    state = cancellable_stream

    def decode(wav, _rate):
        state.connection.client_abort = True
        return wav

    monkeypatch.setattr(streaming, "_wav_chunk_to_pcm", decode)
    state.tts.to_tts_stream("旧片段", opus_handler=state.packets.append)
    assert state.packets == state.queued == []
    assert state.closed and state.resets == 1


def test_new_turn_after_first_chunk_discards_tail_without_replay(cancellable_stream, monkeypatch):
    state = cancellable_stream

    def chunks(_raw, **_kwargs):
        yield b"abcdef"
        state.connection.sentence_id = "new"

    monkeypatch.setattr(streaming, "iter_wav_chunks", chunks)
    state.tts.to_tts_stream("旧片段", opus_handler=state.packets.append)
    assert state.packets == [b"first", b"second"]
    assert len(state.queued) == 1
    assert state.closed and state.resets == 1


def test_new_turn_during_encoding_drops_remaining_packets(cancellable_stream):
    state = cancellable_stream

    def packet(value):
        state.packets.append(value)
        state.connection.sentence_id = "new"

    state.tts.to_tts_stream("旧片段", opus_handler=packet)
    assert state.packets == [b"first"]
    assert state.queued == [("first", None, "旧片段", "old")]
    assert state.closed and state.resets == 1


def test_network_failure_after_abort_does_not_trigger_full_wav_fallback(cancellable_stream, monkeypatch):
    state = cancellable_stream

    def post(*_args, **_kwargs):
        state.connection.client_abort = True
        raise OSError("connection closed")

    monkeypatch.setattr(streaming, "_open_stream", post)
    state.tts.to_tts_stream("旧片段", opus_handler=state.packets.append)
    assert state.packets == state.queued == []
    assert state.resets == 1


def test_new_turn_during_full_wav_fallback_discards_audio_without_retry(cancellable_stream, monkeypatch):
    state = cancellable_stream
    state.connection.logger = SimpleNamespace(bind=lambda **_kwargs: SimpleNamespace(warning=lambda _text: None))
    fallback_calls = []

    def post(*_args, **_kwargs):
        raise OSError("stream failed")

    def fallback(text, opus_handler):
        fallback_calls.append(text)
        state.connection.sentence_id = "new"
        # 回调必须正常返回，否则上游会将取消误判为失败重试。
        opus_handler(b"late")
        opus_handler(b"also-late")

    state.fallback = fallback
    monkeypatch.setattr(streaming, "_open_stream", post)
    state.tts.to_tts_stream("旧片段", opus_handler=state.packets.append)
    assert fallback_calls == ["旧片段"]
    assert state.packets == []
    assert state.resets == 2
