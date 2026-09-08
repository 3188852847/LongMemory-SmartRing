"""启动首选项只保存便利信息，不扩大高风险权限。"""

import importlib.util
from pathlib import Path

import pytest


PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/development/launcher/preferences.py"
)
spec = importlib.util.spec_from_file_location("launcher_preferences_test", PATH)
preferences = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preferences)


def test_preferences_roundtrip_and_never_persist_delete_permission(tmp_path):
    path = tmp_path / "launcher.json"
    preferences.save_preferences(path, {
        "voice": True,
        "start_page": "settings",
        "database": "D:/synthetic.db",
        "voice_root": "D:/xiaozhi",
        "lan_ip": "192.168.1.8",
        "role": "plain_v1",
        "memory_extraction": "llm",
        "memory_retrieval": "hybrid",
        "memory_consolidation": True,
        "embedding_model_dir": "D:/bge",
        "tts_backend": "voxcpm2",
        "http_risk_ack": True,
        "allow_memory_delete": True,
        "api_key": "must-not-be-written",
    })

    raw = path.read_text(encoding="utf-8")
    loaded = preferences.load_preferences(path)
    assert loaded["voice"] is True
    assert loaded["start_page"] == "settings"
    assert loaded["memory_retrieval"] == "hybrid"
    assert loaded["memory_consolidation"] is True
    assert loaded["http_risk_ack"] is True
    assert "allow_memory_delete" not in raw
    assert "must-not-be-written" not in raw


def test_local_launcher_delete_default_is_explicit_but_not_persisted():
    assert preferences.DEFAULT_SESSION_ALLOW_MEMORY_DELETE is True
    assert "allow_memory_delete" not in preferences.DEFAULTS


def test_legacy_ip_only_file_and_broken_file_are_safe(tmp_path):
    path = tmp_path / "launcher.json"
    path.write_text('{"lan_ip":"192.168.1.9"}', encoding="utf-8")
    loaded = preferences.load_preferences(path)
    assert loaded["lan_ip"] == "192.168.1.9"
    assert loaded["http_risk_ack"] is False

    path.write_text("not-json", encoding="utf-8")
    assert preferences.load_preferences(path) == preferences.DEFAULTS


def test_unknown_choice_is_rejected_before_write(tmp_path):
    with pytest.raises(ValueError, match="launcher_preference_role_invalid"):
        preferences.save_preferences(tmp_path / "launcher.json", {"role": "unknown"})


def test_model_profile_pointer_is_non_secret_and_defaults_safely(tmp_path):
    path = tmp_path / "model-profile.json"
    assert preferences.load_model_profile(path) == "campus"
    preferences.save_model_profile(path, "official")
    assert preferences.load_model_profile(path) == "official"
    assert "api_key" not in path.read_text(encoding="utf-8").lower()
    path.write_text('{"active_profile":"unknown"}', encoding="utf-8")
    assert preferences.load_model_profile(path) == "campus"
