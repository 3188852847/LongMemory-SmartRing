"""豆包备用启动路径的离线验证；只有临时合成配置，不启动真实进程。"""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/launcher"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    result = {}
    for name in ("runtime", "preferences", "view_model"):
        spec = importlib.util.spec_from_file_location("doubao_launcher_test_" + name, DIRECTORY / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        result[name] = module
    return SimpleNamespace(**result)


@pytest.fixture
def options(tmp_path, modules):
    root = tmp_path / "合成项目 path"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").touch()
    (root / ".env.deepseek.local").write_text("# synthetic", encoding="utf-8")
    (root / "synthetic.db").touch()
    voice_root = tmp_path / "合成小智"
    (voice_root / ".venv/Scripts").mkdir(parents=True)
    (voice_root / ".venv/Scripts/python.exe").touch()
    (root / ".env.doubao.local").write_text('DOUBAO_API_KEY="synthetic-secret"\n', encoding="utf-8")
    return modules.runtime.Options(
        root=root, database=root / "synthetic.db", model_profile="official",
        voice=True, voice_mode="doubao_realtime", voice_root=voice_root,
        voice_model_profile="campus", lan_ip="192.168.1.8", tts_backend="cosyvoice3",
        consent=False,
    )


def test_mode_is_saved_without_credentials_and_legacy_defaults_to_pipeline(tmp_path, modules):
    path = tmp_path / "preferences.json"
    assert modules.preferences.load_preferences(path)["voice_mode"] == "pipeline"
    modules.preferences.save_preferences(path, {
        "voice_mode": "doubao_realtime", "tts_backend": "cosyvoice3",
        "DOUBAO_API_KEY": "private-test-value",
    })
    assert modules.preferences.load_preferences(path)["voice_mode"] == "doubao_realtime"
    assert modules.preferences.load_preferences(path)["tts_backend"] == "cosyvoice3"
    assert "private-test-value" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        modules.preferences.save_preferences(path, {"voice_mode": "automatic_cloud"})


def test_cloud_commands_skip_local_models_and_voice_campus_consent(options, modules):
    commands = modules.runtime.build_commands(options, uv="synthetic-uv")
    assert [name for name, _, _ in commands] == ["console", "voice"]
    web, voice = commands[0][1], commands[1][1]
    assert web[web.index("--model-profile") + 1] == "official"
    assert web[web.index("--memory-backend") + 1] == "longmemory"
    assert voice[voice.index("--voice-mode") + 1] == "doubao_realtime"
    assert voice[voice.index("--doubao-env") + 1] == str(options.root / ".env.doubao.local")
    assert "synthetic-secret" not in repr(commands)


def test_cloud_mode_preserves_web_campus_acknowledgment(options, modules):
    with pytest.raises(ValueError, match="HTTP"):
        modules.runtime.build_commands(replace(options, model_profile="campus"), uv="synthetic-uv")


def test_missing_cloud_configuration_blocks_before_services(options, modules, monkeypatch):
    missing = replace(options, doubao_env=options.root / "missing.env")
    calls = []
    monkeypatch.setattr(modules.runtime.shutil, "which", lambda _: "synthetic-uv")
    monkeypatch.setattr(modules.runtime, "OwnedService", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="豆包实时语音尚未完成配置"):
        modules.runtime.Manager().start(missing)
    assert calls == []


def test_cloud_manager_only_syncs_network_and_does_not_pass_memory_token(options, modules, monkeypatch):
    network_calls, spawned = [], []
    monkeypatch.setattr(modules.runtime.shutil, "which", lambda _: "synthetic-uv")
    monkeypatch.setattr(modules.runtime, "require_free", lambda *args: None)
    monkeypatch.setattr(modules.runtime, "require_no_listener", lambda *args: pytest.fail("local TTS port queried"))
    def network_action(*args, **kwargs):
        network_calls.append(kwargs.get("apply", False))
        return {"changed": True}
    monkeypatch.setitem(sys.modules, "network", SimpleNamespace(config_action=network_action))
    for name in ("tts", "model", "memory", "vad"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(
            config_action=lambda *a, **kw: pytest.fail("pipeline provider configuration accessed")
        ))
    def owned(command, cwd, env):
        spawned.append((command, dict(env)))
        return SimpleNamespace(process=SimpleNamespace(poll=lambda: None), stop=lambda: None)
    monkeypatch.setattr(modules.runtime, "OwnedService", owned)
    manager = modules.runtime.Manager()
    manager.start(options)
    assert network_calls == [False, True]
    assert set(manager.services) == {"console", "voice"}
    assert "LONGMEMORY_RUNTIME_TOKEN" in spawned[0][1]
    assert "LONGMEMORY_RUNTIME_TOKEN" not in spawned[1][1]
    assert "LONGMEMORY_RUNTIME_URL" not in spawned[1][1]
    status = json.loads(manager.status_path.read_text(encoding="utf-8"))
    assert status["schema_version"] == 5
    assert status["startup"]["voice_mode"] == "doubao_realtime"
    assert status["startup"]["tts_backend"] is None
    assert status["startup"]["vad_profile"] is None
    assert manager.local_tts_ready() is False
    with pytest.raises(ValueError, match="请先停止"):
        manager.start(replace(options, voice_mode="pipeline"))
    manager.stop()


def test_voice_wrapper_routes_cloud_without_loading_yaml_or_providers(options, modules, monkeypatch):
    spec = importlib.util.spec_from_file_location("doubao_launcher_voice_test", DIRECTORY / "voice.py")
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    captured = []
    monkeypatch.setitem(sys.modules, "setup", SimpleNamespace(main=lambda: captured.append(list(sys.argv)) or 0))
    monkeypatch.setitem(sys.modules, "yaml", None)
    monkeypatch.setattr(sys, "argv", ["voice.py", str(options.root), str(options.voice_root), str(options.database),
                                      options.lan_ip, "cosyvoice3", "longmemory",
                                      "--voice-mode", "doubao_realtime"])
    original_path = list(sys.path)
    try:
        assert wrapper.main() == 0
    finally:
        sys.path[:] = original_path
    command = captured[0]
    assert command[command.index("--voice-mode") + 1] == "doubao_realtime"
    assert "--device-control" in command
    assert "--tts-backend" not in command
    assert "--allow-insecure-http" not in command


def test_cloud_presentation_does_not_claim_local_or_cloud_connection_ready(modules):
    view = modules.view_model
    summary = view.summary_text(True, "chat", "plain_v1", "rules", "keyword", "cosyvoice3",
                                False, False, model_profile="official", voice_mode="doubao_realtime")
    assert "语音发往云端" in summary and "长期记忆暂不接入" in summary
    assert "CosyVoice" not in summary
    starting = view.starting_services(voice=True, tts_backend="cosyvoice3", model_profile="official",
                                     voice_model_profile="campus", memory_backend="longmemory",
                                     voice_mode="doubao_realtime")
    assert "学校模型" not in starting["message"]
    ready = view.ready_services(voice=True, tts_backend="cosyvoice3", local_tts_ready=False,
                               opened=True, voice_mode="doubao_realtime")
    assert "云端连接待实测" in ready["components"]["speech"][0]
    assert "CosyVoice" not in repr(ready)


def test_text_only_does_not_require_cloud_configuration(options, modules):
    result = modules.runtime.build_commands(replace(options, voice=False,
                                                    doubao_env=options.root / "missing.env"), uv="synthetic-uv")
    assert [name for name, _, _ in result] == ["console"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Tk panel")
def test_secret_dialog_is_blank_and_saves_only_on_user_action(tmp_path, modules, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    monkeypatch.setitem(sys.modules, "runtime", modules.runtime)
    spec = importlib.util.spec_from_file_location("doubao_launcher_dialog_test", DIRECTORY / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    saved, notifications = [], []
    monkeypatch.setattr(app, "doubao_config_module", lambda: SimpleNamespace(
        save_credentials=lambda path, *, api_key: saved.append((path, api_key))
    ))
    window = tk.Tk()
    window.withdraw()
    try:
        path = tmp_path / "synthetic.env"
        dialog = app.open_doubao_configuration(window, path, lambda: notifications.append("saved"))
        dialog.withdraw()
        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)
        widgets = list(children(dialog))
        entry = next(widget for widget in widgets if isinstance(widget, ttk.Entry))
        assert entry.get() == ""
        assert entry.cget("show") == "●"
        assert saved == []
        entry.insert(0, "synthetic-new-key")
        button = next(widget for widget in widgets if isinstance(widget, ttk.Button)
                      and widget.cget("text") == "保存到本机")
        button.invoke()
        assert saved == [(path, "synthetic-new-key")]
        assert notifications == ["saved"]
        assert not dialog.winfo_exists()
    finally:
        window.destroy()
