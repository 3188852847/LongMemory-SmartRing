"""启动首选项只保存便利信息，不扩大高风险权限。"""

import importlib.util
from pathlib import Path
import sys

import pytest


PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/development/launcher/preferences.py"
)
spec = importlib.util.spec_from_file_location("launcher_preferences_test", PATH)
preferences = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(PATH.parent))
try:
    spec.loader.exec_module(preferences)
finally:
    sys.path.pop(0)


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
        "l1_sufficiency_shadow": True,
        "l2_sufficiency_shadow": True,
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
    assert loaded["l1_sufficiency_shadow"] is True
    assert loaded["l2_sufficiency_shadow"] is True
    assert loaded["http_risk_ack"] is True
    assert "allow_memory_delete" not in raw
    assert "must-not-be-written" not in raw


def test_local_launcher_delete_default_is_explicit_but_not_persisted():
    assert preferences.DEFAULT_SESSION_ALLOW_MEMORY_DELETE is True
    assert "allow_memory_delete" not in preferences.DEFAULTS


def test_fresh_launcher_uses_daily_cosyvoice_default(tmp_path):
    assert preferences.DEFAULTS["tts_backend"] == "cosyvoice3"
    assert preferences.load_tts_backend(tmp_path / "missing-selection.json") == "cosyvoice3"


@pytest.mark.parametrize('mode', ['buffered', 'incremental', 'adaptive'])
def test_cosy_mode_persists_and_reopens_without_changing_other_voice_settings(tmp_path, mode):
    path = tmp_path/'launcher.json'
    original = {**preferences.DEFAULTS, 'voice': True, 'cosy_delivery_mode': mode,
                'voice_latency_mode': 'original', 'tts_backend': 'cosyvoice3'}
    preferences.save_preferences(path, original)
    reopened = preferences.load_preferences(path)
    assert reopened['cosy_delivery_mode'] == mode
    assert reopened['voice'] and reopened['voice_latency_mode'] == 'original'
    assert reopened['tts_backend'] == 'cosyvoice3'


@pytest.mark.parametrize('bad', ['unknown', '', None, [], {}, True, 1])
def test_bad_optional_cosy_mode_loads_buffered_and_save_rejects_before_overwrite(tmp_path, bad):
    import json
    path = tmp_path/'launcher.json'
    path.write_text(json.dumps({'version': 7, 'cosy_delivery_mode': bad, 'role': 'plain_v1'}), 'utf-8')
    before = path.read_bytes()
    assert preferences.load_preferences(path)['cosy_delivery_mode'] == 'buffered'
    with pytest.raises(ValueError, match='cosy_delivery_mode_invalid'):
        preferences.save_preferences(path, {'cosy_delivery_mode': bad})
    assert path.read_bytes() == before


def test_version7_missing_cosy_field_keeps_old_defaults_and_original_bytes(tmp_path):
    path = tmp_path/'launcher.json'
    path.write_text('{"version":7,"voice_latency_mode":"original","tts_backend":"edge"}', 'utf-8')
    before = path.read_bytes()
    loaded = preferences.load_preferences(path)
    assert loaded['cosy_delivery_mode'] == 'buffered'
    assert loaded['voice_latency_mode'] == 'original' and loaded['tts_backend'] == 'edge'
    assert path.read_bytes() == before


def test_actual_tk_save_callback_preserves_current_hidden_mode_without_opening_tk(tmp_path):
    import ast
    from types import SimpleNamespace
    # 执行实际嵌套保存回调，以合成控件替代GUI；不创建Tk窗口或读取本机偏好。
    app = PATH.with_name('app.py')
    tree = ast.parse(app.read_text('utf-8'))
    callback = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'current_preferences')
    path = tmp_path/'launcher.json'
    values = {**preferences.DEFAULTS, 'cosy_delivery_mode': 'adaptive'}
    preferences.save_preferences(path, values)
    namespace = dict(load_preferences=preferences.load_preferences, choice_path=path,
                     saved=dict(preferences.DEFAULTS), start_page_labels={'chat': 'chat'})
    for name in ('voice', 'memory_consolidation', 'l1_sufficiency_shadow', 'l2_sufficiency_shadow', 'consent'):
        namespace[name] = SimpleNamespace(get=lambda: False)
    for name in ('database', 'server', 'ip', 'embedding_model', 'sanotts_source'):
        namespace[name] = SimpleNamespace(get=lambda: '')
    namespace['start_page'] = SimpleNamespace(get=lambda: 'chat')
    choices = dict(selected_voice_mode='pipeline', selected_voice_latency_mode='realtime',
                   selected_role='elysia_v1', selected_extraction='rules', selected_retrieval='keyword',
                   selected_tts='cosyvoice3', selected_vad_profile='normal')
    for name, value in choices.items():
        namespace[name] = lambda value=value: value
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(app), 'exec'), namespace)
    current = namespace['current_preferences']()
    assert current['cosy_delivery_mode'] == 'adaptive'
    preferences.save_preferences(path, current)
    assert preferences.load_preferences(path)['cosy_delivery_mode'] == 'adaptive'


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
    assert preferences.load_model_profile(path, "voice") == "campus"
    preferences.save_model_profile(path, "official", "voice")
    assert preferences.load_model_profile(path, "voice") == "official"
    assert "api_key" not in path.read_text(encoding="utf-8").lower()
    path.write_text('{"active_profile":"unknown"}', encoding="utf-8")
    assert preferences.load_model_profile(path) == "campus"


def test_memory_backend_pointer_defaults_and_rejects_unknown_values(tmp_path):
    path = tmp_path / "memory-backend.json"
    assert preferences.load_memory_backend(path) == "longmemory"
    preferences.save_memory_backend(path, "xiaozhi_local")
    assert preferences.load_memory_backend(path) == "xiaozhi_local"
    with pytest.raises(ValueError, match="launcher_memory_backend_invalid"):
        preferences.save_memory_backend(path, "unknown")


def test_tts_backend_pointer_migrates_legacy_fallback_and_rejects_unknown(tmp_path):
    path = tmp_path / "tts-backend.json"
    assert preferences.load_tts_backend(path, "sanotts") == "sanotts"
    preferences.save_tts_backend(path, "voxcpm2")
    assert preferences.load_tts_backend(path, "sanotts") == "voxcpm2"
    assert "key" not in path.read_text(encoding="utf-8").lower()
    with pytest.raises(ValueError, match="launcher_tts_backend_invalid"):
        preferences.save_tts_backend(path, "unknown")
