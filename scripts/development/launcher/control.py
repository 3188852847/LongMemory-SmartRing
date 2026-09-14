"""启动面板的受限本机控制通道；只开放状态、启动与停止。"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import threading


CONTROL_FILE_NAME = "launcher-control.json"
ALLOWED_ACTIONS = frozenset({"status", "start", "stop"})
MAX_REQUEST_BYTES = 4096


class LauncherControl:
    """在既有单实例 socket 上验权，并把操作交回 Tk 主线程。"""

    def __init__(self, listener: socket.socket, path: Path, *, token: str | None = None):
        self.listener = listener
        self.path = path
        self.token = token or secrets.token_urlsafe(32)
        self._pending = deque()
        self._pending_lock = threading.Lock()
        self._closed = threading.Event()
        self.listener.settimeout(0.25)
        self._publish()
        self._thread = threading.Thread(
            target=self._serve,
            name="launcher-local-control",
            daemon=True,
        )
        self._thread.start()

    def _publish(self) -> None:
        payload = {
            "schema_version": 1,
            "host": "127.0.0.1",
            "port": int(self.listener.getsockname()[1]),
            "token": self.token,
            "launcher_pid": os.getpid(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actions": sorted(ALLOWED_ACTIONS),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _read_request(connection: socket.socket) -> bytes:
        chunks = []
        total = 0
        while total <= MAX_REQUEST_BYTES:
            part = connection.recv(min(1024, MAX_REQUEST_BYTES + 1 - total))
            if not part:
                break
            chunks.append(part)
            total += len(part)
            if b"\n" in part:
                break
        if total > MAX_REQUEST_BYTES:
            raise ValueError("request_too_large")
        return b"".join(chunks).split(b"\n", 1)[0]

    @staticmethod
    def _send(connection: socket.socket, payload: dict) -> None:
        connection.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                connection, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(2)
                if address[0] != "127.0.0.1":
                    self._send(connection, {"ok": False, "error": "loopback_required"})
                    continue
                try:
                    request = json.loads(self._read_request(connection))
                    supplied = request.get("token") if isinstance(request, dict) else None
                    action = request.get("action") if isinstance(request, dict) else None
                    if not isinstance(supplied, str) or not secrets.compare_digest(
                        supplied, self.token
                    ):
                        response = {"ok": False, "error": "unauthorized"}
                    elif not isinstance(action, str) or action not in ALLOWED_ACTIONS:
                        response = {"ok": False, "error": "action_not_allowed"}
                    else:
                        completed = threading.Event()
                        box = {}
                        with self._pending_lock:
                            self._pending.append((action, completed, box))
                        if not completed.wait(timeout=30):
                            response = {"ok": False, "error": "launcher_busy"}
                        else:
                            response = box["response"]
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    response = {"ok": False, "error": "invalid_request"}
                try:
                    self._send(connection, response)
                except OSError:
                    pass

    def poll(self, dispatch) -> int:
        """由 Tk 主线程调用；单次排空有限队列，所有 UI 操作保持线程归属。"""
        # 文件可能被手工清理或被一次失败的外部维护误删。监听器与令牌仍只
        # 属于当前进程；缺失时原子重发，使控制入口无需重启面板即可恢复。
        # 已存在的文件绝不覆盖，避免抢占另一个实例或掩盖未知内容。
        if not self.path.exists():
            try:
                self._publish()
            except OSError:
                pass
        handled = 0
        while handled < 8:
            with self._pending_lock:
                if not self._pending:
                    break
                action, completed, box = self._pending.popleft()
            try:
                response = dispatch(action)
                if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                    response = {"ok": False, "error": "invalid_dispatch_result"}
            except Exception:
                response = {"ok": False, "error": "launcher_action_failed"}
            box["response"] = response
            completed.set()
            handled += 1
        return handled

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._thread.join(timeout=1)
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if saved.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def request_control(path: Path, action: str, *, timeout: float = 35) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("launcher_control_action_invalid")
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
        host = target["host"]
        port = target["port"]
        token = target["token"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("launcher_control_unavailable") from error
    if host != "127.0.0.1" or type(port) is not int or not 1024 <= port <= 65535:
        raise RuntimeError("launcher_control_invalid")
    if not isinstance(token, str) or len(token) < 32:
        raise RuntimeError("launcher_control_invalid")
    payload = json.dumps({"token": token, "action": action}).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(payload)
            response = LauncherControl._read_request(connection)
        result = json.loads(response)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("launcher_control_unavailable") from error
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise RuntimeError("launcher_control_invalid_response")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ALLOWED_ACTIONS))
    parser.add_argument(
        "--control-file",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data/control" / CONTROL_FILE_NAME,
    )
    args = parser.parse_args()
    try:
        result = request_control(args.control_file, args.action)
    except (RuntimeError, ValueError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
