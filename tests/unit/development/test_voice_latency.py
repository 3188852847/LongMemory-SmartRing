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
    connection.sentence_id = "private-sentence"
    tracker = voice_latency.VoiceLatencyTracker(connection, clock=lambda: next(ticks))
    tracker.begin()
    tracker.bind_sentence()
    tracker.mark("llm_requested_ms")
    tracker.mark("llm_first_output_ms")
    result = tracker.snapshot()
    assert result["tts_backend"] == "edge"
    assert result["timings_ms"]["llm_requested_ms"] == 200
    assert result["timings_ms"]["llm_first_output_ms"] == 500
    rendered = repr(result) + " ".join(connection.logger.lines)
    assert "private-sentence" not in rendered


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
