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
def options(tmp_path, modules, monkeypatch):
    root = tmp_path / "合成项目 path"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").touch()
    (root / "local/config/.env.deepseek.local").parent.mkdir(parents=True, exist_ok=True)
    (root / "local/config/.env.deepseek.local").write_text("# synthetic", encoding="utf-8")
    (root / "synthetic.db").touch()
    voice_root = tmp_path / "合成小智"
    (voice_root / ".venv/Scripts").mkdir(parents=True)
    (voice_root / ".venv/Scripts/python.exe").touch()
    (root / "local/config/.env.doubao.local").parent.mkdir(parents=True, exist_ok=True)
    (root / "local/config/.env.doubao.local").write_text('DOUBAO_API_KEY="synthetic-secret"\n', encoding="utf-8")
    from longmemory.infrastructure.config import hy_deployment
    source = root / "data/databases/hy-sources.db"
    source.parent.mkdir(parents=True)
    source.touch()
    state = root / "data/memory/hy-daily"
    state.mkdir(parents=True)
    (state / "hy-state.json").write_text("{}")
    monkeypatch.setattr(hy_deployment, "load_hy_deployment", lambda root: SimpleNamespace(
        source_path=source, state_directory=state))
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


def test_hy_screen_rejects_nonmemory_voice_chain(options, modules):
    with pytest.raises(ValueError, match="Hy 圆屏"):
        modules.runtime.build_commands(options, uv="synthetic-uv")


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
    summary = view.summary_text(True, "chat", "plain_v1", "cosyvoice3",
                                False, model_profile="official", voice_mode="doubao_realtime")
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
def test_secret_dialog_is_blank_and_saves_only_on_user_action(in_tk_subprocess, tmp_path, modules, monkeypatch):
    if not in_tk_subprocess:
        return
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
