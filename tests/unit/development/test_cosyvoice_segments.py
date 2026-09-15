"""只用合成文本与替身检查边界、调度、取消；不加载模型或访问网络。"""

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
from cosyvoice_segments import install_cosyvoice_punctuation_policy, install_cosyvoice_ready_segment_drain


FIRST = "好的，我们先把今天最重要的事情慢慢说清楚，"
SECOND = "接下来再一起决定应该怎样安排后面的事情，"
THIRD = "最后也记得给自己留下一点安静休息的时间。"


class FakeTTS:
    def __init__(self):
        self.conn = SimpleNamespace(sentence_id="turn-1", client_abort=False, stop_event=threading.Event())
        self.current_sentence_id = "turn-1"
        self.tts_text_buff = []
        self.processed_chars = 0
        self.is_first_sentence = True
        self.tts_stop_request = False
        self.spoken = []
        self.packets = []
        self.after_speech = lambda: None

    def _get_segment_text(self):
        pytest.fail("CosyVoice must not depend on the upstream rfind boundary")

    def _process_remaining_text_stream(self, opus_handler=None):
        pytest.fail("upstream tail strips punctuation and adds the whole buffer length")

    def to_tts_stream(self, text, opus_handler=None):
        self.spoken.append(text)
        if opus_handler:
            opus_handler(b"synthetic-opus")
        self.after_speech()
        return "single-segment-result"

    def handle_opus(self, packet):
        self.packets.append(packet)


def install(tts):
    install_cosyvoice_punctuation_policy(tts)
    install_cosyvoice_ready_segment_drain(tts, tts.conn)


def text_increment(tts, text):
    # 忠实保留上游 TEXT 每次只调用一次 get 的行为；余段必须由项目调度器立即接上。
    tts.tts_text_buff.append(text)
    segment = tts._get_segment_text()
    if segment:
        return tts.to_tts_stream(segment, opus_handler=tts.handle_opus)
    return None


@pytest.mark.parametrize("chunk_size", [1, 3, 500])
def test_increment_size_does_not_change_first_or_later_boundaries(chunk_size):
    tts = FakeTTS()
    install(tts)
    text = FIRST + SECOND + THIRD + "就这样。"
    for start in range(0, len(text), chunk_size):
        text_increment(tts, text[start:start + chunk_size])
    assert tts.spoken == [FIRST, SECOND, THIRD]
    assert tts._process_remaining_text_stream(opus_handler=tts.handle_opus)
    assert tts.spoken == [FIRST, SECOND, THIRD, "就这样。"]
    assert not tts._process_remaining_text_stream(opus_handler=tts.handle_opus)
    assert tts.processed_chars == len(text)


@pytest.mark.parametrize("chunk_size", [1, 500])
def test_first_clause_already_eight_characters_is_not_forced_to_sixteen(chunk_size):
    tts = FakeTTS()
    install(tts)
    first = "我们现在先看一下时间，"
    assert 8 <= len(first) < 16
    for start in range(0, len(first), chunk_size):
        text_increment(tts, first[start:start + chunk_size])
    assert tts.spoken == [first]


def test_closed_segments_are_drained_without_next_text_or_last_message():
    tts = FakeTTS()
    install(tts)
    result = text_increment(tts, FIRST + SECOND + THIRD)
    assert result == "single-segment-result"
    assert tts.spoken == [FIRST, SECOND, THIRD]
    assert len(tts.packets) == 3


def test_long_unpunctuated_text_is_never_hard_cut():
    tts = FakeTTS()
    install(tts)
    text_increment(tts, "这些文字虽然很长但是没有合适的自然边界所以不能从中间切开" * 5)
    assert tts.spoken == []
    assert tts.processed_chars == 0
    assert tts._process_remaining_text_stream()
    assert len(tts.spoken) == 1


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_empty_or_whitespace_input_never_synthesizes(text):
    tts = FakeTTS()
    install(tts)
    text_increment(tts, text)
    assert not tts._process_remaining_text_stream()
    assert tts.spoken == []
    assert tts.processed_chars == len(text)


def test_reentrant_final_flush_cannot_replay_uncommitted_tail():
    tts = FakeTTS()
    install(tts)
    nested_results = []
    tts.after_speech = lambda: nested_results.append(tts._process_remaining_text_stream())
    text_increment(tts, "你好呀，我在呢。")
    assert tts._process_remaining_text_stream()
    assert nested_results == [False]
    assert tts.spoken == ["你好呀，我在呢。"]
    assert not tts._process_remaining_text_stream()


@pytest.mark.parametrize("kind", ["abort", "new_turn", "tts_stop", "connection_stop"])
def test_cancel_after_first_segment_stops_drain_without_consuming_next(kind):
    tts = FakeTTS()
    install(tts)

    def cancel():
        if kind == "abort":
            tts.conn.client_abort = True
        elif kind == "new_turn":
            tts.conn.sentence_id = "turn-2"
        elif kind == "tts_stop":
            tts.tts_stop_request = True
        else:
            tts.conn.stop_event.set()

    tts.after_speech = cancel
    text_increment(tts, FIRST + SECOND)
    assert tts.spoken == [FIRST]
    assert tts.processed_chars == len(FIRST)
    assert not tts._process_remaining_text_stream()


def test_stale_turn_with_abort_reset_is_rejected_before_measured_call():
    tts = FakeTTS()
    install(tts)
    tts.tts_text_buff = [FIRST + SECOND]
    first = tts._get_segment_text()
    tts.conn.sentence_id = "turn-2"
    tts.conn.client_abort = False
    tts.to_tts_stream(first)
    assert tts.spoken == []
    assert tts.processed_chars == len(FIRST)


def test_file_tail_and_following_text_keep_offsets_without_replay():
    tts = FakeTTS()
    install(tts)
    text_increment(tts, FIRST + "这就是尾文。")
    assert tts._process_remaining_text_stream()
    assert tts.spoken == [FIRST, "这就是尾文。"]
    before = tts.processed_chars
    assert not tts._process_remaining_text_stream()
    text_increment(tts, SECOND + "文件之后的尾文。")
    assert tts._process_remaining_text_stream()
    assert tts.spoken == [FIRST, "这就是尾文。", SECOND, "文件之后的尾文。"]
    assert tts.processed_chars == before + len(SECOND + "文件之后的尾文。")
    assert not tts._process_remaining_text_stream()


def test_flush_and_drain_guards_are_released_after_exception():
    tts = FakeTTS()
    calls = []

    def failing(text, **_kwargs):
        calls.append(text)
        raise RuntimeError("synthetic failure")

    tts.to_tts_stream = failing
    install(tts)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        text_increment(tts, FIRST + "尾文。")
    state = tts._longmemory_cosy_segment_state
    assert not state.local.draining
    with pytest.raises(RuntimeError, match="synthetic failure"):
        tts._process_remaining_text_stream()
    assert not state.local.flushing
    # 失败的尾文尚未提交偏移，重试仍只看到尾文；不会重复首段。
    assert calls == [FIRST, "尾文。"]
    assert tts.processed_chars == len(FIRST)


def test_actual_v6_installer_keeps_each_drained_segment_separate(monkeypatch):
    import cosyvoice_streaming
    import voice_latency

    tts = FakeTTS()
    connection = tts.conn
    connection.tts = tts
    connection.config = {"selected_module": {"TTS": "CustomTTS"}, "TTS": {"CustomTTS": {"url": "http://127.0.0.1:18770/v1/audio/speech"}}}
    connection.logger = SimpleNamespace(bind=lambda **_kwargs: SimpleNamespace(info=lambda _text: None))
    connection.sentence_id = "previous"
    tracker = voice_latency.VoiceLatencyTracker(connection)
    connection._longmemory_voice_latency = tracker
    tracker.begin()
    connection.sentence_id = "turn-1"
    monkeypatch.setattr(cosyvoice_streaming, "install_cosyvoice_streaming", lambda *_args: None)
    voice_latency._observe_components(connection)
    text_increment(tts, FIRST + SECOND + THIRD)
    segments = tracker.snapshot()["tts_segments"]
    assert [segment["index"] for segment in segments] == [1, 2, 3]
    assert [segment["opus_packets"] for segment in segments] == [1, 1, 1]
    assert all(segment["duration_ms"] is not None for segment in segments)
    assert tts.spoken == [FIRST, SECOND, THIRD]
