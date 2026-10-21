import concurrent.futures
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time
from collections import deque
from types import SimpleNamespace


DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/launcher"
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location(
        "launcher_control_test", DIRECTORY / "control.py"
    )
    control_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control_module)
finally:
    sys.path.pop(0)


def _listener():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener


def _receive_line(connection):
    chunks = []
    while True:
        part = connection.recv(1024)
        if not part:
            break
        chunks.append(part)
        if b"\n" in part:
            break
    return b"".join(chunks).split(b"\n", 1)[0]


def test_authenticated_request_is_dispatched_on_polling_thread(tmp_path):
    listener = _listener()
    path = tmp_path / "launcher-control.json"
    bridge = control_module.LauncherControl(listener, path, token="x" * 43)
    dispatched = []
    try:
        published = json.loads(path.read_text(encoding="utf-8"))
        assert published["host"] == "127.0.0.1"
        assert published["port"] == listener.getsockname()[1]
        assert published["actions"] == ["start", "status", "stop"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(control_module.request_control, path, "status")
            deadline = time.monotonic() + 2
            while not future.done() and time.monotonic() < deadline:
                bridge.poll(lambda action: (
                    dispatched.append(action) or
                    {"ok": True, "state": "stopped", "ready": False}
                ))
                time.sleep(0.01)
            assert future.result(timeout=1) == {
                "ok": True, "state": "stopped", "ready": False,
            }
        assert dispatched == ["status"]
    finally:
        bridge.close()
        listener.close()
    assert not path.exists()


def test_wrong_token_and_unlisted_action_never_reach_dispatch(tmp_path):
    listener = _listener()
    path = tmp_path / "launcher-control.json"
    bridge = control_module.LauncherControl(listener, path, token="y" * 43)
    try:
        with socket.create_connection(listener.getsockname(), timeout=2) as connection:
            connection.sendall(b'{"token":"wrong","action":"stop"}\n')
            assert json.loads(_receive_line(connection)) == {
                "ok": False, "error": "unauthorized",
            }
        with socket.create_connection(listener.getsockname(), timeout=2) as connection:
            connection.sendall(
                json.dumps({"token": "y" * 43, "action": "cleanup"}).encode() + b"\n"
            )
            assert json.loads(_receive_line(connection)) == {
                "ok": False, "error": "action_not_allowed",
            }
        with socket.create_connection(listener.getsockname(), timeout=2) as connection:
            connection.sendall(
                json.dumps({"token": "y" * 43, "action": ["stop"]}).encode() + b"\n"
            )
            assert json.loads(_receive_line(connection)) == {
                "ok": False, "error": "action_not_allowed",
            }
        # 畸形操作不能杀死监听线程，后续合法请求仍应进入主线程队列。
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(control_module.request_control, path, "status")
            deadline = time.monotonic() + 2
            while not future.done() and time.monotonic() < deadline:
                bridge.poll(lambda _action: {"ok": True, "state": "stopped"})
                time.sleep(0.01)
            assert future.result(timeout=1) == {"ok": True, "state": "stopped"}
        assert bridge.poll(lambda _action: {"ok": True}) == 0
    finally:
        bridge.close()
        listener.close()


def test_client_rejects_non_loopback_discovery_and_unknown_action(tmp_path):
    path = tmp_path / "launcher-control.json"
    path.write_text(json.dumps({
        "host": "192.0.2.1", "port": 18767, "token": "z" * 43,
    }), encoding="utf-8")
    try:
        control_module.request_control(path, "status")
    except RuntimeError as error:
        assert str(error) == "launcher_control_invalid"
    else:
        raise AssertionError("non-loopback discovery must be rejected")

    try:
        control_module.request_control(path, "cleanup")
    except ValueError as error:
        assert str(error) == "launcher_control_action_invalid"
    else:
        raise AssertionError("unlisted action must be rejected")


def test_timed_out_queued_request_is_cancelled_instead_of_running_later(tmp_path):
    listener = _listener()
    path = tmp_path / "launcher-control.json"
    bridge = control_module.LauncherControl(
        listener, path, token="q" * 43, response_timeout_seconds=0.05,
    )
    dispatched = []
    try:
        result = control_module.request_control(path, "start", timeout=1)
        assert result == {"ok": False, "error": "launcher_busy"}
        assert bridge.poll(lambda action: dispatched.append(action) or {"ok": True}) == 0
        assert dispatched == []
    finally:
        bridge.close()
        listener.close()


def test_request_that_already_started_reports_unknown_outcome_on_timeout(tmp_path, monkeypatch):
    # 此例验证服务端已开始操作后的超时语义。真实TCP/验权另有覆盖；
    # 不把50ms线程调度或额外1s客户端期限当作dispatch已开始的证据。
    path = tmp_path / "launcher-control.json"
    path.write_text("{}", encoding="utf-8")
    bridge = control_module.LauncherControl.__new__(control_module.LauncherControl)
    bridge.path, bridge.token = path, "r" * 43
    bridge.response_timeout_seconds = 0.05
    bridge._pending, bridge._pending_lock = deque(), threading.Lock()
    bridge._closed = threading.Event()
    release = threading.Event()
    entered = threading.Event()
    dispatched, responses, pending_requests, polling = [], [], [], []

    def dispatch(action):
        dispatched.append(action)
        entered.set()
        assert release.wait(timeout=5), "test did not release the running action"
        return {"ok": True, "state": "starting"}

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def settimeout(self, _): pass
        def recv(self, _):
            return json.dumps({"token": bridge.token, "action": "start"}).encode() + b"\n"
        def sendall(self, raw):
            responses.append(json.loads(raw))
            bridge._closed.set()  # 单个合成连接结束后停止真实_serve循环。

    connection = Connection()
    bridge.listener = SimpleNamespace(accept=lambda: (connection, ("127.0.0.1", 12345)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        class Completion:
            def wait(self, timeout):
                assert timeout == 0.05
                pending_requests.append(bridge._pending[0])
                polling.append(executor.submit(bridge.poll, dispatch))
                assert entered.wait(timeout=5), "dispatch never started"
                # 显式让逻辑等待到期：不用真实50ms去赌poll线程能否先取得队列。
                return False
            def set(self): pass
        # 只替换被测模块的Event工厂，不修改全局threading或业务源码。
        monkeypatch.setattr(control_module, "threading", SimpleNamespace(Event=Completion))
        try:
            bridge._serve()
            assert responses == [{
                "ok": False, "error": "launcher_action_outcome_unknown",
            }]
            assert pending_requests[0]["state"] == "running"
        finally:
            release.set()
        assert polling[0].result(timeout=5) == 1
    assert dispatched == ["start"]
    assert pending_requests[0]["state"] == "completed"
    assert pending_requests[0]["response"] == {"ok": True, "state": "starting"}
    assert len(responses) == 1  # 操作继续完成，但不向已答复的调用者伪发第二个结果。
