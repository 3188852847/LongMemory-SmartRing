import asyncio
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_latency.py"
SPEC = importlib.util.spec_from_file_location("voice_latency_test", SCRIPT)
voice_latency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice_latency)


class BoundLogger:
    def __init__(self, lines): self.lines = lines
    def info(self, line): self.lines.append(line)
    def error(self, line): self.lines.append(line)


class Logger:
    def __init__(self): self.lines = []
    def bind(self, **_kwargs): return BoundLogger(self.lines)


def test_tracker_exposes_only_fixed_timing_fields_and_not_content():
    ticks = iter([1.0, 1.2, 1.5])
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    connection.sentence_id = "previous-private-sentence"
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: next(ticks))
    tracker.begin()
    # 上一轮迟到的回调不能抢占新样本；新 sentence_id 才能建立归属。
    tracker.bind_sentence("previous-private-sentence")
    tracker.mark("llm_requested_ms", sentence_id="previous-private-sentence")
    connection.sentence_id = "private-sentence"
    tracker.bind_sentence()
    tracker.mark("llm_requested_ms")
    tracker.mark("llm_first_output_ms")
    result = tracker.snapshot()
    assert result["version"] == 6
    assert result["response_path"] == "model"
    assert result["tts_backend"] == "edge"
    assert result["timings_ms"]["llm_requested_ms"] == 200
    assert result["timings_ms"]["llm_first_output_ms"] == 500
    rendered = repr(result) + " ".join(connection.logger.lines)
    assert "private-sentence" not in rendered


def test_tracker_rejects_late_completion_from_previous_turn():
    ticks = iter([1.0, 2.0, 3.0, 4.0])
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    connection.sentence_id = "turn-0"
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: next(ticks))
    old_token = tracker.begin()
    connection.sentence_id = "turn-1"
    tracker.bind_sentence()
    new_token = tracker.begin()
    connection.sentence_id = "turn-2"
    tracker.bind_sentence()
    tracker.mark("response_completed_ms", token=old_token, sentence_id="turn-1")
    assert tracker.snapshot()["timings_ms"]["response_completed_ms"] is None
    tracker.mark("response_completed_ms", token=new_token, sentence_id="turn-2")
    assert tracker.snapshot()["timings_ms"]["response_completed_ms"] == 1000


def test_tracker_marks_preset_path_without_content():
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    tracker = voice_latency.VoiceLatencyTracker(connection)
    tracker.begin()
    tracker.set_response_path("preset")
    assert tracker.snapshot()["response_path"] == "preset"


def test_tracker_claims_fresh_asr_input_timing_once():
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    connection._longmemory_voice_input_pending = {
        "expires_at": 2.0,
        "input_timings_ms": {"vad_endpoint_ms": 700, "asr_processing_ms": 320},
    }
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: 1.0)
    tracker.begin()
    assert tracker.snapshot()["version"] == 6
    assert tracker.snapshot()["input_timings_ms"]["asr_processing_ms"] == 320
    tracker.begin()
    assert "input_timings_ms" not in tracker.snapshot()


def test_tracker_keeps_latest_audible_turn_when_empty_turn_follows():
    ticks = iter([1.0, 1.3, 2.0, 2.2])
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    connection.sentence_id = "turn-0"
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: next(ticks))
    tracker.begin()
    connection.sentence_id = "turn-1"
    tracker.bind_sentence()
    tracker.mark("first_audio_sent_ms", sentence_id="turn-1")
    audible = tracker.snapshot()
    assert audible["timings_ms"]["first_audio_sent_ms"] == 300

    tracker.begin()
    connection.sentence_id = "turn-2"
    tracker.bind_sentence()
    tracker.mark("memory_ready_ms", sentence_id="turn-2")
    assert tracker.snapshot() == audible


def test_edge_first_chunk_policy_flushes_only_first_unpunctuated_chunk():
    class TTS:
        def __init__(self):
            self.tts_text_buff = []
            self.processed_chars = 0
            self.is_first_sentence = True

        def _get_segment_text(self):
            return None

    tts = TTS()
    voice_latency.install_edge_first_chunk_policy(tts, maximum_chars=18)
    text = "这是一段没有标点而且长度已经足够触发首句提前合成的回答"
    tts.tts_text_buff.append(text)
    assert tts._get_segment_text() == text[:18]
    assert tts.processed_chars == 18
    assert tts.is_first_sentence is False
    # 后续文本仍交还上游原始切句策略，不继续按固定字符强拆。
    assert tts._get_segment_text() is None


def test_cosyvoice_uses_natural_punctuation_without_fixed_character_split():
    class TTS:
        def __init__(self):
            self.tts_text_buff = []
            self.processed_chars = 0
            self.is_first_sentence = True
            self.punctuations = ("。", "？")

        def _get_segment_text(self):
            if self.is_first_sentence and self.tts_text_buff:
                self.is_first_sentence = False
                self.processed_chars = len(self.tts_text_buff[0])
                return self.tts_text_buff[0]
            return None

    tts = TTS()
    voice_latency.install_cosyvoice_punctuation_policy(tts)
    tts.tts_text_buff.append("你好，")
    assert tts._get_segment_text() == "你好，"
    # 后续短逗号不立即创建新 TTS 请求；累计足够内容后仍只在标点处切。
    tts.tts_text_buff.extend(["今天辛苦了，", "我们先休息一下，", "再慢慢聊聊吧。"])
    assert tts._get_segment_text() == "今天辛苦了，我们先休息一下，再慢慢聊聊吧。"
    assert tts.processed_chars == len("你好，今天辛苦了，我们先休息一下，再慢慢聊聊吧。")
    assert tts._get_segment_text() is None
    # 没有标点的长文本也不能按固定字数硬切。
    tts.tts_text_buff.append("这部分即使很长也要继续等待自然语言边界")
    assert tts._get_segment_text() is None
    assert tts._longmemory_punctuation_policy == "cosyvoice3"
    assert tts._longmemory_punctuation_minimum_chars == 18


def test_cosyvoice_punctuation_policy_rejects_too_small_segments():
    with pytest.raises(ValueError, match="punctuation_segment_limit_invalid"):
        voice_latency.install_cosyvoice_punctuation_policy(object(), minimum_chars=7)


@pytest.mark.parametrize("single_increment", [False, True])
def test_cosyvoice_final_flush_respects_boundaries_for_large_llm_increments(single_increment):
    first = "好的，"
    segments = [
        "我们先把今天最重要的事情慢慢说清楚，",
        "接下来再一起决定应该怎样安排后面的事情，",
        "最后也记得给自己留下一点安静休息的时间。",
    ]
    tail = "就这样"

    class TTS:
        def __init__(self):
            self.tts_text_buff = [first]
            self.processed_chars = len(first)
            self.is_first_sentence = False
            self.tts_stop_request = False
            self.spoken = []

        def _get_segment_text(self):
            return None

        def to_tts_stream(self, text, opus_handler=None):
            self.spoken.append(text)

        def _process_remaining_text_stream(self, opus_handler=None):
            full_text = "".join(self.tts_text_buff)
            remaining = full_text[self.processed_chars:]
            if not remaining:
                return False
            self.to_tts_stream(remaining, opus_handler=opus_handler)
            # 保留当前 Xiaozhi 上游的全缓冲累加语义，不能在替身里先修好它。
            self.processed_chars += len(full_text)
            return True

    tts = TTS()
    voice_latency.install_cosyvoice_punctuation_policy(tts)
    rest = "".join(segments) + tail
    for increment in [rest] if single_increment else list(rest):
        tts.tts_text_buff.append(increment)
        segment = tts._get_segment_text()
        if segment:
            tts.to_tts_stream(segment)
    # 模拟上游 LAST/FILE；不能把整份剩余文字绕过自然切段一次合成。
    assert tts._process_remaining_text_stream()
    assert tts.spoken == [*segments, tail]
    assert tts.processed_chars == len(first + rest)
    assert tts._process_remaining_text_stream() is False
    # 同一轮 FILE 会清空余文但不重置文本缓冲；后续 TEXT 仍应完整合成。
    continuation = "播放插入的音频之后继续说话"
    tts.tts_text_buff.append(continuation)
    assert tts._process_remaining_text_stream() is True
    assert tts.spoken == [*segments, tail, continuation]
    assert tts.processed_chars == len(first + rest + continuation)
    assert tts._process_remaining_text_stream() is False


def test_cosyvoice_final_flush_stops_when_cancelled_between_segments():
    class TTS:
        tts_text_buff = ["我们先把今天最重要的事情慢慢说清楚，后面这一部分不应该继续合成。"]
        processed_chars = 0
        is_first_sentence = False
        tts_stop_request = False

        def _get_segment_text(self):
            return None

        def to_tts_stream(self, text, opus_handler=None):
            self.spoken = text
            self.tts_stop_request = True

        def _process_remaining_text_stream(self, opus_handler=None):
            pytest.fail("cancelled flush must not synthesize the tail")

    tts = TTS()
    voice_latency.install_cosyvoice_punctuation_policy(tts)
    assert tts._process_remaining_text_stream() is True
    assert tts.spoken == "我们先把今天最重要的事情慢慢说清楚，"


def test_first_chunk_policy_keeps_ascii_words_whole():
    class TTS:
        tts_text_buff = ["please remember LongMemory project details"]
        processed_chars = 0
        is_first_sentence = True

        def _get_segment_text(self):
            return None

    tts = TTS()
    voice_latency.install_first_chunk_policy(
        tts, maximum_chars=18, marker="test"
    )
    assert tts._get_segment_text() == "please remember"
    assert tts.processed_chars == len("please remember ")


def test_installed_observer_measures_model_tts_and_audio_without_text_in_logs():
    class LLM:
        def response(self, *_args, **_kwargs):
            yield "private-answer"

    class TTS:
        current_sentence_id = "turn-1"
        def to_tts_stream(self, _text, **_kwargs):
            self.handle_opus(b"private-audio")
            self.handle_opus(b"private-audio")
            return None
        def handle_opus(self, _packet): return None

    class Connection:
        def chat(self, _query, depth=0):
            self.sentence_id = "turn-1"
            list(self.llm.response("session", []))
            self.tts.to_tts_stream("private-answer")
            self.tts.handle_opus(b"private-audio")

    voice_latency.install_voice_latency(Connection)
    connection = Connection()
    connection.config = {"selected_module": {"TTS": "CustomTTS"}, "TTS": {"CustomTTS": {
        "url": "http://127.0.0.1:18768/v1/audio/speech"
    }}}
    connection.logger = Logger()
    connection.llm, connection.tts = LLM(), TTS()
    connection.chat("private-question")
    result = connection._longmemory_voice_latency.snapshot()
    assert result["tts_backend"] == "voxcpm2"
    assert result["timings_ms"]["llm_first_output_ms"] is not None
    assert result["timings_ms"]["tts_started_ms"] is not None
    assert result["timings_ms"]["audio_ready_ms"] is not None
    assert len(result["tts_segments"]) == 1
    assert result["tts_segments"][0]["duration_ms"] is not None
    assert result["tts_segments"][0]["opus_packets"] == 2
    assert result["tts_segments"][0]["audio_duration_ms"] == 120
    assert "private" not in " ".join(connection.logger.lines)

    async def original(*_args, **_kwargs): return "sent"
    measured = voice_latency.observed_audio_sender(original)
    assert asyncio.run(measured(connection, object(), b"packet", None, "turn-1")) == "sent"
    assert connection._longmemory_voice_latency.snapshot()["timings_ms"]["first_audio_sent_ms"] is not None


def test_model_stream_failure_is_classified_without_exposing_error_text():
    class PrivateHttpError(Exception):
        status_code = 404

    class LLM:
        def response(self, *_args, **_kwargs):
            yield ""
            raise PrivateHttpError("private provider response")

    class Connection:
        def chat(self, _query, depth=0):
            self.sentence_id = "turn-failed"
            list(self.llm.response("session", []))

    voice_latency.install_voice_latency(Connection)
    connection = Connection()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    connection.llm, connection.tts = LLM(), None

    try:
        connection.chat("private question")
    except PrivateHttpError:
        pass

    result = connection._longmemory_voice_latency.snapshot()
    assert result["version"] == 6
    assert result["state"] == "failed"
    assert result["failure"]["stage"] == "model"
    assert result["failure"]["code"] == "model_http_404"
    assert "private" not in repr(result) + " ".join(connection.logger.lines)


def test_memory_failure_is_recorded_with_fixed_code():
    ticks = iter([1.0, 1.25])
    connection = type("Connection", (), {})()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}}
    connection.logger = Logger()
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: next(ticks))
    tracker.begin()
    tracker.fail("memory_response_invalid", stage="memory")
    result = tracker.snapshot()
    assert result["state"] == "failed"
    assert result["failure"] == {
        "stage": "memory", "code": "memory_response_invalid", "at_ms": 250,
    }
