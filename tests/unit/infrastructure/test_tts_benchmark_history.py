import json

import pytest

from longmemory.infrastructure.config.tts_benchmark_history import TTSBenchmarkHistory


def result(backend="sanotts", case_id="short_reply", completed=1050.5):
    return {
        "backend": backend, "case": {"id": case_id},
        "started_at": "2026-09-11T01:02:03+00:00", "adapter_delivery": "buffered",
        "first_audio_available_ms": completed, "completed_ms": completed,
        "audio_bytes": 100396, "content_type": "audio/wav",
        "wave": {"duration_seconds": 2.2756, "near_silent": False},
    }


def test_history_persists_cross_backend_results_without_audio_or_text(tmp_path):
    path = tmp_path / "data/control/tts-benchmark-history.json"
    history = TTSBenchmarkHistory(path)
    first = history.append(result())
    second = history.append(result("edge", completed=800.0))
    runs = history.list_runs()
    assert [item["id"] for item in runs] == [second, first]
    assert [item["backend"] for item in runs] == ["edge", "sanotts"]
    raw = path.read_text(encoding="utf-8")
    assert "好呀" not in raw and "RIFF" not in raw


def test_invalid_history_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"schema_version": 999, "runs": []}), encoding="utf-8")
    history = TTSBenchmarkHistory(path)
    with pytest.raises(ValueError, match="tts_benchmark_history_invalid"):
        history.append(result())
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 999
