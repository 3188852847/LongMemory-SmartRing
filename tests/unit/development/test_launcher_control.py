import concurrent.futures
import importlib.util
import json
from pathlib import Path
import socket
import sys
import time


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
