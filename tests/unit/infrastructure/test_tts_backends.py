import pytest

from longmemory.infrastructure.config.tts_backends import TTSBackendStore


def test_tts_selection_defaults_to_current_and_persists_only_pointer(tmp_path):
    store = TTSBackendStore(tmp_path, current_backend="sanotts")
    assert store.selected() == "sanotts"
    result = store.select("edge", voice_running=True)
    assert result["next_start_backend"] == "edge"
    assert result["restart_required"] is True
    raw = store.selection_path.read_text(encoding="utf-8")
    assert "api_key" not in raw.lower() and "path" not in raw.lower()


def test_tts_selection_rejects_unknown_backend(tmp_path):
    store = TTSBackendStore(tmp_path)
    with pytest.raises(ValueError, match="unknown_tts_backend"):
        store.select("unknown")
