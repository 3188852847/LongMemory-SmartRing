"""响应策略从面板到语音子进程的合成验证，不接触真实配置或模型。"""

from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/launcher"
XIAOZHI = DIRECTORY.parent / "xiaozhi"


class SyntheticConnection:
    pass


def load_module(monkeypatch, path):
    # 脚本按其真实同级导入环境加载，不借其他测试收集时留下的sys.path。
    monkeypatch.syspath_prepend(str(XIAOZHI))
    monkeypatch.syspath_prepend(str(DIRECTORY))
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("latency_launcher_test_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    return SimpleNamespace(**{name: load_module(monkeypatch, DIRECTORY / (name + ".py"))
                              for name in ("runtime", "preferences")})


@pytest.fixture
def options(tmp_path, modules):
    root = tmp_path / "synthetic project"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").touch()
    (root / "local/config/.env.deepseek.local").parent.mkdir(parents=True, exist_ok=True)
    (root / "local/config/.env.deepseek.local").write_text("# synthetic", encoding="utf-8")
    (root / "synthetic.db").touch()
    server = tmp_path / "synthetic server"
    (server / ".venv/Scripts").mkdir(parents=True)
    (server / ".venv/Scripts/python.exe").touch()
    return modules.runtime.Options(root=root, database=root / "synthetic.db", model_profile="official",
                                   voice=True, voice_root=server, voice_model_profile="official",
                                   lan_ip="192.168.1.8", tts_backend="edge")


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_choice_roundtrip_and_legacy_default(tmp_path, modules, mode):
    path = tmp_path / "preferences.json"
    path.write_text('{"version": 5, "voice": true}', encoding="utf-8")
    assert modules.preferences.load_preferences(path)["voice_latency_mode"] == "realtime"
    modules.preferences.save_preferences(path, {"voice_latency_mode": mode})
    assert modules.preferences.load_preferences(path)["voice_latency_mode"] == mode
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 7
    with pytest.raises(ValueError, match="voice_latency_mode"):
        modules.preferences.save_preferences(path, {"voice_latency_mode": "unknown"})
    assert modules.preferences.load_preferences(path)["voice_latency_mode"] == mode


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_only_voice_command_gets_response_mode(options, modules, mode):
    commands = modules.runtime.build_commands(replace(options, voice_latency_mode=mode), uv="synthetic-uv")
    web, voice = commands[0][1], commands[-1][1]
    assert "--voice-latency-mode" not in web
    assert voice[voice.index("--voice-latency-mode") + 1] == mode
    with pytest.raises(ValueError, match="响应策略"):
        modules.runtime.build_commands(replace(options, voice_latency_mode="unknown"), uv="synthetic-uv")


def test_cloud_commands_do_not_get_pipeline_response_mode(options, modules, monkeypatch):
    monkeypatch.setattr(modules.runtime, "validate_doubao_config", lambda _: None)
    commands = modules.runtime.build_commands(replace(options, voice_mode="doubao_realtime"), uv="synthetic-uv")
    assert all("--voice-latency-mode" not in command for _, command, _ in commands)


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_voice_wrapper_passes_mode_to_setup(options, monkeypatch, mode):
    module = load_module(monkeypatch, DIRECTORY / "voice.py")
    captured = []
    (options.voice_root / "data").mkdir()
    (options.voice_root / "data/.config.yaml").write_text("# synthetic", encoding="utf-8")
    monkeypatch.setattr(module, "memory_contract_matches", lambda *args: True)
    monkeypatch.setattr(module, "tts_matches", lambda *args: True)
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(safe_load=lambda _: {}))
    monkeypatch.setitem(sys.modules, "setup", SimpleNamespace(
        validate_config=lambda *args, **kwargs: None,
        install_memory_provider=lambda *args, **kwargs: None,
        main=lambda: captured.append(list(sys.argv)) or 0,
    ))
    monkeypatch.setattr(sys, "argv", ["voice.py", str(options.root), str(options.voice_root),
                                      str(options.database), options.lan_ip, "edge", "longmemory",
                                      "--voice-latency-mode", mode])
    previous = list(sys.path)
    try:
        assert module.main() == 0
    finally:
        sys.path[:] = previous
    assert captured[0][captured[0].index("--voice-latency-mode") + 1] == mode


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_setup_passes_mode_to_adapter_only(tmp_path, monkeypatch, mode):
    module = load_module(monkeypatch, XIAOZHI / "setup.py")
    server = tmp_path / "synthetic server"
    (server / "data").mkdir(parents=True)
    (server / "data/.config.yaml").write_text("# synthetic", encoding="utf-8")
    python = server / ".venv/Scripts/python.exe"
    config = {"server": {"ip": "127.0.0.1"}, "selected_module": {"Memory": "LongMemory"}}
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(safe_load=lambda _: config))
    monkeypatch.setattr(module, "validate_config", lambda *args, **kwargs: {"base_url": "https://example.invalid/v1"})
    provider = server / 'core/providers/memory/longmemory/longmemory.py'
    provider.parent.mkdir(parents=True)
    provider.write_bytes((XIAOZHI / 'longmemory_provider.py').read_bytes())
    monkeypatch.setattr(module, "prepare_environment", lambda *args: {"SYNTHETIC": "1"})
    monkeypatch.setattr(sys, "executable", str(python))
    monkeypatch.setattr(sys, "argv", ["setup.py", "start", "--server-dir", str(server),
                                      "--voice-latency-mode", mode])
    captured = []
    monkeypatch.setattr(module.subprocess, "call", lambda command, **kwargs: captured.append(command) or 0)
    assert module.main() == 0
    assert captured[0][1].endswith("launch_with_memory.py")
    assert captured[0][captured[0].index("--voice-latency-mode") + 1] == mode


def test_original_mode_never_imports_extra_pipeline_components(monkeypatch):
    module = load_module(monkeypatch, XIAOZHI / "launch_with_memory.py")
    monkeypatch.setenv("LONGMEMORY_VOICE_RESPONSE_STYLE", "synthetic-previous")
    # helper 的单项默认仍保持隔离；日用 main 显式启用已通过基准的预识别。
    monkeypatch.setitem(sys.modules, "core.providers.asr", None)
    module.install_pipeline_latency_policy(SyntheticConnection, mode="realtime")
    assert os.environ["LONGMEMORY_VOICE_RESPONSE_STYLE"] == "realtime"
    assert SyntheticConnection._longmemory_voice_latency_mode == "realtime"
    module.install_pipeline_latency_policy(SyntheticConnection, mode="original", enable_asr_prefetch=True,
                                          enable_http_keepalive=True)
    assert os.environ["LONGMEMORY_VOICE_RESPONSE_STYLE"] == "original"
    assert SyntheticConnection._longmemory_voice_latency_mode == "original"
    with pytest.raises(ValueError, match="voice_latency_mode_invalid"):
        module.install_pipeline_latency_policy(SyntheticConnection, mode="unknown")


def test_validated_prefetch_can_be_enabled_for_realtime_only(monkeypatch):
    module = load_module(monkeypatch, XIAOZHI / "launch_with_memory.py")
    monkeypatch.setenv("LONGMEMORY_VOICE_RESPONSE_STYLE", "synthetic-previous")
    calls, fun_local = [], object()
    monkeypatch.setitem(sys.modules, "core.providers.asr", SimpleNamespace(fun_local=fun_local))
    monkeypatch.setitem(sys.modules, "voice_asr_prefetch", SimpleNamespace(
        install_voice_asr_prefetch=lambda *args, **kwargs: calls.append((args, kwargs))))
    module.install_pipeline_latency_policy(SyntheticConnection, mode="realtime", enable_asr_prefetch=True)
    assert calls == [((SyntheticConnection, fun_local), {"enabled": True})]


def test_http_keepalive_installer_has_separate_enable_switch(monkeypatch):
    module = load_module(monkeypatch, XIAOZHI / "launch_with_memory.py")
    monkeypatch.setenv("LONGMEMORY_VOICE_RESPONSE_STYLE", "synthetic-previous")
    calls, provider = [], object()
    monkeypatch.setitem(sys.modules, "core.providers.llm.openai", SimpleNamespace(openai=provider))
    monkeypatch.setitem(sys.modules, "voice_http_transport", SimpleNamespace(
        install_voice_http_transport=lambda *args, **kwargs: calls.append((args, kwargs))))
    module.install_pipeline_latency_policy(SyntheticConnection, mode="realtime")
    assert calls == []
    module.install_pipeline_latency_policy(SyntheticConnection, mode="realtime", enable_http_keepalive=True)
    assert calls == [((provider,), {"enabled": True})]


def test_cloud_bootstrap_does_not_set_pipeline_style_or_import_asr(tmp_path, monkeypatch):
    module = load_module(monkeypatch, XIAOZHI / "launch_with_memory.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LONGMEMORY_VOICE_RESPONSE_STYLE", "synthetic-untouched")
    monkeypatch.setattr(sys, "argv", ["launch_with_memory.py", "--voice-mode", "doubao_realtime"])
    monkeypatch.setitem(sys.modules, "control_compatibility", SimpleNamespace(verify_control_snapshot=lambda _: None))
    connection_class = type("Connection", (), {})
    monkeypatch.setitem(sys.modules, "core.connection", SimpleNamespace(ConnectionHandler=connection_class))
    monkeypatch.setitem(sys.modules, "direct_ws_v2", SimpleNamespace(install_direct_ws_v2=lambda _: None))
    monkeypatch.setitem(sys.modules, "doubao_realtime.config", SimpleNamespace(load_config=lambda _: "synthetic-config"))
    monkeypatch.setitem(sys.modules, "doubao_realtime.bootstrap", SimpleNamespace(install_realtime_mode=lambda *args: None))
    monkeypatch.setitem(sys.modules, "core.providers.asr", None)
    monkeypatch.setattr(module.runpy, "run_path", lambda *args, **kwargs: None)
    previous = list(sys.path)
    try:
        module.main()
    finally:
        sys.path[:] = previous
    assert os.environ["LONGMEMORY_VOICE_RESPONSE_STYLE"] == "synthetic-untouched"


@pytest.mark.parametrize("mode", ["realtime", "original"])
def test_pipeline_bootstrap_installs_input_timing_before_response_policy(tmp_path, monkeypatch, mode):
    module = load_module(monkeypatch, XIAOZHI / "launch_with_memory.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["launch_with_memory.py", "--voice-latency-mode", mode])
    calls = []
    connection_class = type("Connection", (), {})
    monkeypatch.setitem(sys.modules, "core.connection", SimpleNamespace(ConnectionHandler=connection_class))
    monkeypatch.setitem(sys.modules, "direct_ws_v2", SimpleNamespace(install_direct_ws_v2=lambda _: None))
    receive_audio = SimpleNamespace()
    handle = SimpleNamespace(receiveAudioHandle=receive_audio, sendAudioHandle=SimpleNamespace())
    monkeypatch.setitem(sys.modules, "voice_waiting", SimpleNamespace(install_waiting_sender=lambda _: None))
    monkeypatch.setitem(sys.modules, "core", SimpleNamespace(handle=handle))
    monkeypatch.setitem(sys.modules, "core.handle", handle)
    monkeypatch.setitem(sys.modules, "core.handle.receiveAudioHandle", receive_audio)
    monkeypatch.setitem(sys.modules, "core.providers.memory.longmemory.longmemory", SimpleNamespace(MemoryProvider=object))
    monkeypatch.setitem(sys.modules, "fast_voice_responses", SimpleNamespace(install_fast_voice_responses=lambda _: None))
    monkeypatch.setitem(sys.modules, "voice_latency", SimpleNamespace(
        install_voice_latency=lambda _: None, install_audio_send_observer=lambda: None))
    monkeypatch.setitem(sys.modules, "voice_input_latency", SimpleNamespace(
        install_voice_input_latency=lambda _: calls.append("input_timing")))
    monkeypatch.setitem(sys.modules, "voice_prediction", SimpleNamespace(install_voice_prediction_shadow=lambda _: None))
    monkeypatch.setitem(sys.modules, "voice_persistent_session", SimpleNamespace(
        install_persistent_device_session=lambda *_args: calls.append("persistent_session")))
    monkeypatch.setitem(sys.modules, "core.providers.asr", SimpleNamespace(base=object))
    monkeypatch.setattr(module, "isolate_memory_initialization", lambda *args: None)
    monkeypatch.setattr(module, "install_answer_completion", lambda *args: None)
    monkeypatch.setattr(module, "install_voice_output_revocation_policy", lambda *args: calls.append("revocation"))
    monkeypatch.setattr(module, "install_internal_end_prompt_boundary", lambda *args: None)
    monkeypatch.setattr(module, "install_pipeline_latency_policy",
                        lambda *args, **kwargs: calls.append((
                            "policy", kwargs["mode"], kwargs["enable_asr_prefetch"], kwargs["enable_http_keepalive"])))
    monkeypatch.setattr(module.runpy, "run_path", lambda *args, **kwargs: calls.append("run"))
    previous = list(sys.path)
    try:
        module.main()
    finally:
        sys.path[:] = previous
    assert calls == ["input_timing", ("policy", mode, True, True),
                     "persistent_session", "revocation", "run"]


@pytest.mark.parametrize("relative", ["launcher/voice.py", "xiaozhi/setup.py", "xiaozhi/launch_with_memory.py"])
def test_each_cli_rejects_unknown_mode_before_loading_private_configuration(monkeypatch, relative):
    path = DIRECTORY.parent / relative
    module = load_module(monkeypatch, path)
    args = [str(path)]
    if path.name == "voice.py":
        args.extend(["synthetic-project", "synthetic-server", "synthetic-db", "192.168.1.8", "edge", "none"])
    elif path.name == "setup.py":
        args.append("start")
    monkeypatch.setattr(sys, "argv", [*args, "--voice-latency-mode", "unknown"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows Tk panel")
def test_panel_response_choice_saves_and_disables_in_cloud(tmp_path, modules, monkeypatch):
    # 与防火墙面板验收一致：日用面板在独立进程创建 Tk。Windows Tcl 会在
    # 第一次销毁 root 后缓存含中文的库路径，第二次 Tk 构造可能乱码化。
    # 将整个合成 UI 场景隔离，避免其他面板测试的进程状态影响配置路径验收。
    if os.environ.get("LONGMEMORY_TEST_LATENCY_PANEL_CHILD") != "1":
        import subprocess
        env = os.environ.copy()
        env["LONGMEMORY_TEST_LATENCY_PANEL_CHILD"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(Path(__file__).resolve()) + "::test_panel_response_choice_saves_and_disables_in_cloud",
             "--basetemp", str(tmp_path / "panel-child"), "-q"],
            cwd=Path(__file__).resolve().parents[3], env=env,
            capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout.decode("utf-8", errors="replace")
        return
    import tkinter as tk
    from tkinter import ttk
    monkeypatch.setitem(sys.modules, "runtime", modules.runtime)
    app = load_module(monkeypatch, DIRECTORY / "app.py")
    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(app, "Singleton", lambda: SimpleNamespace(socket=None, close=lambda: None))
    monkeypatch.setattr(app, "LauncherControl", lambda *args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(app, "Manager", lambda: SimpleNamespace(services={}, stop=lambda: None))
    real_tk = tk.Tk

    def hidden_window():
        window = real_tk()
        window.withdraw()

        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)

        def inspect_panel():
            window.update_idletasks()
            combos = [widget for widget in children(window) if isinstance(widget, ttk.Combobox)]
            strategy = next(widget for widget in combos if "实时优先" in widget.cget("values"))
            assert strategy.get() == "实时优先"
            strategy.set("原策略（对照）")
            saved = modules.preferences.load_preferences(tmp_path / "local/config/preferences/launcher.json")
            assert saved["voice_latency_mode"] == "original"
            mode = next(widget for widget in combos if "豆包实时语音（备用）" in widget.cget("values"))
            mode.set("豆包实时语音（备用）")
            assert str(strategy.cget("state")) == "disabled"
            mode.set("现有语音链路")
            assert str(strategy.cget("state")) == "readonly"
            assert strategy.get() == "原策略（对照）"
            window.destroy()

        window.mainloop = inspect_panel
        return window

    monkeypatch.setattr(tk, "Tk", hidden_window)
    app.main()
