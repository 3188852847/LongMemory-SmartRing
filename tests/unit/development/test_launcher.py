"""启动器合成验证：不启动小智、不读个人库、不访问校园模型。"""

from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import asyncio

import pytest

DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/launcher"
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location("launcher_runtime_test", DIRECTORY / "runtime.py")
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime
    spec.loader.exec_module(runtime)
finally:
    sys.path.pop(0)


@pytest.fixture
def options(tmp_path):
    root = tmp_path / "中文 path"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").touch()
    (root / ".env").write_text("# synthetic only", encoding="utf-8")
    database = root / "synthetic.db"
    database.touch()  # 只测文件预检，数据库 schema 仍由真实入口独立校验。
    return runtime.Options(root=root, database=database, consent=True)


def test_command_preserves_paths_and_does_not_enable_deletion_or_jobs(options):
    name, cmd, cwd = runtime.build_commands(options, uv="synthetic-uv")[0]
    assert name == "console" and cwd == options.root.resolve()
    assert str(options.database) in cmd
    assert cmd[cmd.index('--env-file') + 1] == '.env'
    assert "--no-sync" in cmd and "--offline" in cmd
    assert "--allow-memory-delete" not in cmd
    assert "--allow-memory-correction" in cmd
    assert "--enable-experiment-runs" not in cmd
    assert "--enable-memory-consolidation" not in cmd
    assert "--chat-provider" in cmd
    assert cmd[cmd.index("--memory-extraction") + 1] == "rules"
    assert cmd[cmd.index("--memory-retrieval") + 1] == "keyword"
    assert "--embedding-model-dir" not in cmd
    assert "--allow-insecure-http" not in cmd  # 网页仍需 .env 的独立 HTTP 许可。
    assert cmd[cmd.index("--memory-backend") + 1] == "longmemory"


def test_explicit_launcher_choice_enables_l1_delete_capability(options):
    cmd = runtime.build_commands(
        replace(options, allow_memory_delete=True), uv="synthetic-uv"
    )[0][1]

    assert cmd.count("--allow-memory-delete") == 1


def test_official_profile_uses_separate_env_file_and_needs_no_http_ack(options):
    (options.root / ".env.deepseek.local").write_text("# synthetic", encoding="utf-8")
    cmd = runtime.build_commands(
        replace(options, model_profile="official", consent=False), uv="synthetic-uv"
    )[0][1]
    assert cmd[cmd.index("--env-file") + 1] == ".env.deepseek.local"
    assert cmd[cmd.index("--model-profile") + 1] == "official"


def test_explicit_launcher_choice_enables_single_consolidation_owner(options):
    cmd = runtime.build_commands(
        replace(options, enable_memory_consolidation=True), uv="synthetic-uv"
    )[0][1]

    assert cmd.count("--enable-memory-consolidation") == 1


def test_hybrid_retrieval_requires_and_passes_existing_snapshot(options):
    model = options.root / "synthetic-bge"
    model.mkdir()
    cmd = runtime.build_commands(
        replace(options, memory_retrieval="hybrid", embedding_model_dir=model),
        uv="synthetic-uv",
    )[0][1]
    assert cmd[cmd.index("--memory-retrieval") + 1] == "hybrid"
    assert cmd[cmd.index("--embedding-model-dir") + 1] == str(model.resolve())
    with pytest.raises(ValueError):
        runtime.build_commands(
            replace(options, memory_retrieval="hybrid", embedding_model_dir=model / "missing"),
            uv="synthetic-uv",
        )


@pytest.mark.parametrize("change", [dict(consent=False), dict(port=8000), dict(port=80),
                                    dict(role="bad"), dict(memory_retrieval="bad"),
                                    dict(voice=True, lan_ip="0.0.0.0"),
                                    dict(voice=True, lan_ip="8.8.8.8")])
def test_invalid_options_rejected(options, change):
    with pytest.raises(ValueError):
        runtime.build_commands(replace(options, **change), uv="synthetic-uv")


def test_missing_database_does_not_create_it(options):
    missing = options.root / "missing.db"
    with pytest.raises(ValueError):
        runtime.build_commands(replace(options, database=missing), uv="synthetic-uv")
    assert not missing.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows uv integration')
def test_real_uv_env_file_with_chinese_and_spaces(options, tmp_path):
    import shutil
    uv = shutil.which('uv')
    if not uv:
        pytest.skip('uv not installed')
    command = runtime.build_commands(options, uv=uv)[0][1]
    # 使用实际生成的 env-file 参数，仅查询解释器版本；合成 .env 无密钥。
    command = command[:command.index('python')] + [sys.executable, '--version']
    env = os.environ.copy()
    env['UV_CACHE_DIR'] = str(tmp_path / 'uv-cache')
    service = runtime.OwnedService(command, options.root, env)
    try:
        assert service.process.wait(timeout=15) == 0
    finally:
        service.stop()


def test_voice_command_uses_own_environment(options):
    voice = options.root / "voice"
    (voice / ".venv/Scripts").mkdir(parents=True)
    (voice / ".venv/Scripts/python.exe").touch()
    cmd = runtime.build_commands(replace(options, voice=True, voice_root=voice, lan_ip="192.168.1.2"), uv="synthetic-uv")[1][1]
    assert cmd[0] == str(voice / ".venv/Scripts/python.exe")
    assert cmd[1].endswith("voice.py")
    assert str(options.database.resolve()) in cmd
    assert cmd[-1] == "longmemory"


def test_default_console_url_opens_react_chat():
    assert runtime.console_url(8767) == "http://127.0.0.1:8767/chat-react"
    assert runtime.console_url(8767, "overview") == "http://127.0.0.1:8767/overview"
    assert runtime.console_url(8767, "memories") == "http://127.0.0.1:8767/memories"
    with pytest.raises(ValueError, match="未知控制台起始页"):
        runtime.console_url(8767, "https://example.invalid")


def test_voxcpm_commands_use_isolated_environment_and_start_before_voice(options):
    voice = options.root / "voice"; (voice / ".venv/Scripts").mkdir(parents=True)
    (voice / ".venv/Scripts/python.exe").touch()
    voxcpm = options.root / "scripts/development/voxcpm"
    (voxcpm / ".venv/Scripts").mkdir(parents=True)
    (voxcpm / ".venv/Scripts/python.exe").touch(); (voxcpm / "service.py").touch()
    commands = runtime.build_commands(replace(options, voice=True, voice_root=voice,
                                               lan_ip="192.168.1.2", tts_backend="voxcpm2"),
                                      uv="synthetic-uv")
    assert [item[0] for item in commands] == ["console", "voxcpm2", "voice"]
    assert commands[1][1][0] == str(voxcpm / ".venv/Scripts/python.exe")
    assert commands[1][1][1] == str(voxcpm / "service.py")
    assert commands[2][1][-2:] == ["voxcpm2", "longmemory"]


@pytest.mark.parametrize("mismatch", [None, "database_path", "project_root", "python_executable"])
def test_voice_shared_paths_are_checked_without_loading_private_config(options, mismatch):
    spec = importlib.util.spec_from_file_location("launcher_voice_test", DIRECTORY / "voice.py")
    voice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(voice)
    memory = {"database_path": str(options.database), "project_root": str(options.root),
              "python_executable": str(options.root / ".venv/Scripts/python.exe")}
    memory["type"] = "longmemory"
    config = {"selected_module": {"Memory": "LongMemory"}, "Memory": {"LongMemory": memory}}
    if mismatch:
        memory[mismatch] = str(options.root / "wrong")
    assert voice.memory_contract_matches(config, options.root, options.database, "longmemory") is (mismatch is None)


@pytest.mark.parametrize("backend,provider,provider_type", [
    ("xiaozhi_local", "mem_local_short", "mem_local_short"),
    ("none", "nomem", "nomem"),
])
def test_voice_accepts_builtin_memory_backends_without_losing_control_identity(
        options, backend, provider, provider_type):
    spec = importlib.util.spec_from_file_location("launcher_voice_builtin_test", DIRECTORY / "voice.py")
    voice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(voice)
    longmemory = {"type": "longmemory", "database_path": str(options.database),
                  "project_root": str(options.root),
                  "python_executable": str(options.root / ".venv/Scripts/python.exe")}
    config = {"selected_module": {"Memory": provider},
              "Memory": {"LongMemory": longmemory, provider: {"type": provider_type}}}
    assert voice.memory_contract_matches(config, options.root, options.database, backend)


def test_voice_tts_contract_is_strict():
    spec = importlib.util.spec_from_file_location("launcher_voice_tts_test", DIRECTORY / "voice.py")
    voice = importlib.util.module_from_spec(spec); spec.loader.exec_module(voice)
    config = {"selected_module": {"TTS": "CustomTTS"}, "TTS": {"CustomTTS": {
        "type": "custom", "method": "POST", "url": "http://127.0.0.1:18768/v1/audio/speech",
        "format": "wav", "params": {"input": "{prompt_text}", "response_format": "wav", "stream": False}}}}
    assert voice.tts_matches(config, "voxcpm2")
    config["TTS"]["CustomTTS"]["url"] = "http://example.invalid"
    assert not voice.tts_matches(config, "voxcpm2")
    assert voice.tts_matches({"selected_module": {"TTS": "EdgeTTS"}}, "edge")


def test_memory_observer_records_provider_and_timing_without_content():
    script = DIRECTORY.parent / "xiaozhi/launch_with_memory.py"
    spec = importlib.util.spec_from_file_location("launch_memory_observer_test", script)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)

    class Provider:
        async def query_memory(self, query):
            return "private-memory"

        async def save_memory(self, dialogue, session_id):
            return None

    class BoundLogger:
        def __init__(self, lines): self.lines = lines
        def info(self, line): self.lines.append(line)

    class Logger:
        def __init__(self): self.lines = []
        def bind(self, **_kwargs): return BoundLogger(self.lines)

    connection = type("Connection", (), {})()
    connection.memory = Provider()
    connection.config = {"selected_module": {"Memory": "mem_local_short"}}
    connection.logger = Logger()
    wrapper.observe_memory_operations(connection)
    assert asyncio.run(connection.memory.query_memory("secret-query")) == "private-memory"
    asyncio.run(connection.memory.save_memory(["secret-dialogue"], "secret-session"))
    joined = " ".join(connection.logger.lines)
    assert "mem_local_short" in joined and "记忆查询" in joined and "记忆保存" in joined
    assert "secret" not in joined and "private-memory" not in joined


def test_singleton_and_occupied_port_are_non_destructive():
    lock = runtime.Singleton(port=0)
    port = lock.socket.getsockname()[1]
    try:
        with pytest.raises(ValueError):
            runtime.Singleton(port=port)
        with pytest.raises(ValueError):
            runtime.require_free("127.0.0.1", port)
        assert lock.socket.fileno() != -1
    finally:
        lock.close()
    runtime.require_free("127.0.0.1", port)


def test_voxcpm_listener_check_rejects_listener_but_not_closed_port():
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(ValueError):
            runtime.require_no_listener("127.0.0.1", port)
    finally:
        listener.close()
    runtime.require_no_listener("127.0.0.1", port)


def test_partial_start_rolls_back_only_owned_services(options, monkeypatch):
    calls = []

    class Owned:
        def __init__(self, command, cwd, env):
            if calls:
                raise OSError("synthetic start failure")
            calls.append(self)

        def stop(self):
            calls.append("stopped")

    monkeypatch.setattr(runtime, "build_commands", lambda _: [("console", [], options.root), ("voice", [], options.root)])
    monkeypatch.setattr(runtime, "require_free", lambda *args: None)
    monkeypatch.setattr(runtime, "OwnedService", Owned)
    manager = runtime.Manager()
    with pytest.raises(OSError):
        manager.start(options)
    assert calls[-1] == "stopped" and manager.services == {}


def test_manager_gives_console_and_voice_one_ephemeral_runtime_identity(options, monkeypatch):
    captured = []

    class Owned:
        def __init__(self, command, cwd, env):
            captured.append(env)
        def stop(self): pass

    monkeypatch.setattr(runtime, "build_commands", lambda _: [("console", [], options.root), ("voice", [], options.root)])
    monkeypatch.setattr(runtime, "require_free", lambda *args: None)
    monkeypatch.setattr(runtime, "OwnedService", Owned)
    manager = runtime.Manager()
    try:
        manager.start(options)
        assert len(captured) == 2
        assert captured[0]["LONGMEMORY_MEMORY_TRANSPORT"] == "runtime"
        assert captured[0]["LONGMEMORY_RUNTIME_TOKEN"] == captured[1]["LONGMEMORY_RUNTIME_TOKEN"]
        assert captured[0]["LONGMEMORY_RUNTIME_URL"].endswith("/api/internal/memory/prepare")
    finally:
        manager.stop()


def test_manager_syncs_selected_voice_model_and_memory_after_ports_are_free(options, monkeypatch):
    from types import SimpleNamespace

    calls = []
    memory_calls = []
    network_calls = []
    tts_calls = []
    ordering = []
    voice_root = options.root / "voice"
    (voice_root / ".venv/Scripts").mkdir(parents=True)
    (voice_root / ".venv/Scripts/python.exe").touch()
    (voice_root / "app.py").touch()
    (options.root / ".env.deepseek.local").write_text("synthetic", encoding="utf-8")
    selected = replace(options, voice=True, voice_root=voice_root,
                       lan_ip="192.168.1.9", voice_model_profile="official")

    def model_action(server, project, profile, **kwargs):
        ordering.append("model_apply" if kwargs.get("apply") else "model_check")
        calls.append((server, project, profile, kwargs))
        return {"config_matches": bool(kwargs.get("apply")), "digest": "a" * 64}

    def memory_action(server, project, profile, **kwargs):
        ordering.append("memory_apply" if kwargs.get("apply") else "memory_check")
        memory_calls.append((server, project, profile, kwargs))
        return {"config_matches": bool(kwargs.get("apply")), "digest": "b" * 64}

    def network_action(server, address, apply=False):
        ordering.append("network_apply" if apply else "network_check")
        network_calls.append((server, address, apply))
        return {"changed": not apply, "old_ip": "192.168.1.8"}

    def tts_action(server, project, backend, **kwargs):
        ordering.append("tts_apply" if kwargs.get("apply") else "tts_check")
        tts_calls.append((server, project, backend, kwargs))
        return {"config_matches": bool(kwargs.get("apply")), "digest": "c" * 64}

    class Owned:
        def __init__(self, command, cwd, env): pass
        def stop(self): pass

    monkeypatch.setitem(sys.modules, "model", SimpleNamespace(config_action=model_action))
    monkeypatch.setitem(sys.modules, "memory", SimpleNamespace(config_action=memory_action))
    monkeypatch.setitem(sys.modules, "network", SimpleNamespace(config_action=network_action))
    monkeypatch.setitem(sys.modules, "tts", SimpleNamespace(config_action=tts_action))
    monkeypatch.setattr(runtime, "build_commands", lambda _: [("console", [], options.root)])
    monkeypatch.setattr(runtime, "require_free", lambda *args: ordering.append("port"))
    monkeypatch.setattr(runtime, "OwnedService", Owned)
    manager = runtime.Manager()
    try:
        manager.start(selected)
        assert calls[0][2:] == ("official", {})
        assert calls[1][2] == "official"
        assert calls[1][3] == {"apply": True, "expected_digest": "a" * 64}
        assert memory_calls[0][2:] == ("longmemory", {})
        assert memory_calls[1][2] == "longmemory"
        assert memory_calls[1][3] == {"apply": True, "expected_digest": "b" * 64}
        assert network_calls == [
            (voice_root, "192.168.1.9", False),
            (voice_root, "192.168.1.9", True),
        ]
        assert tts_calls[0][2:] == ("edge", {})
        assert tts_calls[1][2] == "edge"
        assert tts_calls[1][3] == {"apply": True, "expected_digest": "c" * 64}
        # console、8000、8003、8768、8766 五个监听位都通过后，才允许第一次配置检查。
        assert ordering[:5] == ["port"] * 5
        assert ordering[5:] == [
            "network_check", "tts_check", "model_check", "memory_check",
            "network_apply", "tts_apply", "model_apply", "memory_apply",
        ]
    finally:
        manager.stop()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job integration")
def test_job_stops_descendant_but_not_external_process(tmp_path):
    # 孙进程占据合成端口，停止 Job 后端口释放；另一个独立进程仍活着。
    marker = tmp_path / "port.txt"
    child_code = ("import socket,time,pathlib; s=socket.socket(); s.bind(('127.0.0.1',0)); "
                  f"pathlib.Path({str(marker)!r}).write_text(str(s.getsockname()[1])); time.sleep(60)")
    command = [sys.executable, "-c", f"import subprocess,sys; subprocess.call([sys.executable,'-c',{child_code!r}])"]
    external = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    service = None
    try:
        service = runtime.OwnedService(command, tmp_path, os.environ.copy())
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), service.process.poll()
        port = int(marker.read_text())
        with pytest.raises(ValueError):
            runtime.require_free("127.0.0.1", port)
        service.stop()
        # 与控制台关闭测试一致：进程退出和网络栈释放端口不是同一瞬间。
        deadline = time.monotonic() + 5
        while True:
            try:
                runtime.require_free("127.0.0.1", port)
                break
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        assert external.poll() is None
    finally:
        if service is not None:
            service.stop()
        external.terminate()
        external.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job integration")
def test_owned_console_instance_ready_and_shutdown(tmp_path):
    pytest.importorskip("aiohttp")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    manager = runtime.Manager()
    manager.options = runtime.Options(port=port)
    manager.instance = "synthetic-instance"
    env = os.environ.copy()
    env["LONGMEMORY_LAUNCHER_INSTANCE"] = manager.instance
    # 不使用 .env、日常数据库或聊天开关；仅验证本机静态入口与任务生命周期。
    command = [sys.executable, "-m", "longmemory.entrypoints.api", "--port", str(port)]
    try:
        manager.services["console"] = runtime.OwnedService(command, tmp_path, env)
        deadline = time.monotonic() + 15
        while not manager.ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert manager.ready()
        manager.instance = "wrong-instance"
        assert not manager.ready()
    finally:
        manager.stop()
    # Windows 网络栈可能晚于 Job active=0 回收端口；要求有限时间内可重用，
    # 不把“退出的同一瞬间立即 bind”当作进程仍活着。
    deadline = time.monotonic() + 5
    while True:
        try:
            runtime.require_free("127.0.0.1", port)
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@pytest.mark.skipif(os.name != "nt", reason="Windows Tk panel")
def test_panel_constructs_without_starting_services(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    import tkinter as tk
    spec = importlib.util.spec_from_file_location("launcher_app_test", DIRECTORY / "app.py")
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "runtime", runtime)
    spec.loader.exec_module(app)
    real_tk = tk.Tk

    def hidden_window():
        window = real_tk()
        window.withdraw()
        def one_layout_pass():
            window.update_idletasks()
            assert window.winfo_reqwidth() > 0
            window.destroy()
        window.mainloop = one_layout_pass
        return window

    monkeypatch.setattr(tk, "Tk", hidden_window)
    real_lock = runtime.Singleton
    monkeypatch.setattr(app, "Singleton", lambda: real_lock(port=0))
    app.main()


def test_daily_summary_uses_human_labels_instead_of_internal_enums(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    spec = importlib.util.spec_from_file_location("launcher_app_summary_test", DIRECTORY / "app.py")
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "runtime", runtime)
    spec.loader.exec_module(app)

    summary = app._summary_text(True, "memories", "elysia_v1", "llm", "hybrid", "voxcpm2", True, False, "xiaozhi_local")
    assert summary == (
        "网页＋圆屏语音  ·  打开记忆管理  ·  爱莉希雅风格\n"
        "模型辅助提取  ·  关键词＋语义召回  ·  VoxCPM2 本地声音\n"
        "允许单条删除  ·  低频整理关闭  ·  圆屏：小智本地摘要"
    )
    assert not {"elysia_v1", "llm", "hybrid", "voxcpm2"}.intersection(summary.split())


def test_launcher_failure_hint_is_actionable_without_copying_process_output(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    spec = importlib.util.spec_from_file_location("launcher_app_failure_test", DIRECTORY / "app.py")
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "runtime", runtime)
    spec.loader.exec_module(app)

    assert "数据库、模型配置和高级设置" in app._failure_hint([("console", 2)])
    assert "共享路径或配置" in app._failure_hint([("voice", 3)])
    assert "CUDA 和 18768 端口" in app._failure_hint([("voice", 4)])
    combined = app._failure_hint([("console", 2), ("voice", 3)])
    assert "控制台参数" in combined and "圆屏语音" in combined
    assert "stdout" not in combined and "traceback" not in combined


def test_network_sync_preserves_other_configuration_and_backups(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    from sync_network import sync
    pytest.importorskip('yaml')
    config = tmp_path / '.config.yaml'
    original = ('server:\n  ip: 192.168.1.2\n  port: 8000\n'
                '  websocket: ws://192.168.1.2:8000/xiaozhi/v1/\n'
                '  vision_explain: http://192.168.1.2:8003/mcp/vision/explain\n'
                'prompt: |\n  synthetic role\nLLM:\n  key: synthetic-only\n')
    config.write_text(original, encoding='utf-8')
    assert sync(config, '192.168.1.3')['changed']
    assert config.read_text(encoding='utf-8') == original
    sync(config, '192.168.1.3', True)
    assert list(tmp_path.glob('*.bak'))[0].read_text(encoding='utf-8') == original
    assert 'synthetic role' in config.read_text(encoding='utf-8')
    assert not sync(config, '192.168.1.3')['changed']


def test_network_choices_and_rejection(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    from network import load_choice, save_choice, private_ipv4
    path = tmp_path / 'settings.json'
    assert load_choice(path) == ''
    save_choice(path, '192.168.1.3')
    assert load_choice(path) == '192.168.1.3'
    for bad in ['0.0.0.0', '127.0.0.1', '100.64.1.1', 'bad']:
        with pytest.raises(ValueError):
            private_ipv4(bad)


def test_network_sync_rejects_ambiguous_format(monkeypatch):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    from sync_network import updated_text
    pytest.importorskip('yaml')
    with pytest.raises(ValueError):
        updated_text('server: {ip: 192.168.1.2}\n', '192.168.1.3')
