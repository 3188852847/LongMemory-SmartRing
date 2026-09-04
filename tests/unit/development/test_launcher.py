"""启动器合成验证：不启动小智、不读个人库、不访问校园模型。"""

from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

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
    assert "--no-sync" in cmd and "--offline" in cmd
    assert "--allow-memory-delete" not in cmd
    assert "--enable-experiment-runs" not in cmd
    assert "--chat-provider" in cmd
    assert "--allow-insecure-http" not in cmd  # 网页仍需 .env 的独立 HTTP 许可。


@pytest.mark.parametrize("change", [dict(consent=False), dict(port=8000), dict(port=80),
                                    dict(role="bad"), dict(voice=True, lan_ip="0.0.0.0"),
                                    dict(voice=True, lan_ip="8.8.8.8")])
def test_invalid_options_rejected(options, change):
    with pytest.raises(ValueError):
        runtime.build_commands(replace(options, **change), uv="synthetic-uv")


def test_missing_database_does_not_create_it(options):
    missing = options.root / "missing.db"
    with pytest.raises(ValueError):
        runtime.build_commands(replace(options, database=missing), uv="synthetic-uv")
    assert not missing.exists()


def test_voice_command_uses_own_environment(options):
    voice = options.root / "voice"
    (voice / ".venv/Scripts").mkdir(parents=True)
    (voice / ".venv/Scripts/python.exe").touch()
    cmd = runtime.build_commands(replace(options, voice=True, voice_root=voice), uv="synthetic-uv")[1][1]
    assert cmd[0] == str(voice / ".venv/Scripts/python.exe")
    assert cmd[1].endswith("voice.py")
    assert str(options.database.resolve()) in cmd


@pytest.mark.parametrize("mismatch", [None, "database_path", "project_root", "python_executable", "nomem"])
def test_voice_shared_paths_are_checked_without_loading_private_config(options, mismatch):
    spec = importlib.util.spec_from_file_location("launcher_voice_test", DIRECTORY / "voice.py")
    voice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(voice)
    memory = {"database_path": str(options.database), "project_root": str(options.root),
              "python_executable": str(options.root / ".venv/Scripts/python.exe")}
    config = {"selected_module": {"Memory": "LongMemory"}, "Memory": {"LongMemory": memory}}
    if mismatch == "nomem":
        config["selected_module"]["Memory"] = "nomem"
    elif mismatch:
        memory[mismatch] = str(options.root / "wrong")
    assert voice.shared_paths_match(config, options.root, options.database) is (mismatch is None)


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
        runtime.require_free("127.0.0.1", port)
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
