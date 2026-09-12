import asyncio
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_latency.py"
SPEC = importlib.util.spec_from_file_location("voice_latency_test", SCRIPT)
voice_latency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice_latency)


class BoundLogger:
    def __init__(self, lines): self.lines = lines
    def info(self, line): self.lines.append(line)


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


def test_installed_observer_measures_model_tts_and_audio_without_text_in_logs():
    class LLM:
        def response(self, *_args, **_kwargs):
            yield "private-answer"

    class TTS:
        current_sentence_id = "turn-1"
        def to_tts_stream(self, _text, **_kwargs): return None
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
    assert "private" not in " ".join(connection.logger.lines)

    async def original(*_args, **_kwargs): return "sent"
    measured = voice_latency.observed_audio_sender(original)
    assert asyncio.run(measured(connection, object(), b"packet", None, "turn-1")) == "sent"
    assert connection._longmemory_voice_latency.snapshot()["timings_ms"]["first_audio_sent_ms"] is not None
