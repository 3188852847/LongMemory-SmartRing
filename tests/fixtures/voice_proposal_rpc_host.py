"""两个真实子进程验证的HTTP宿主替身；无模型、个人库、正式prepare。"""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import sys
from threading import Lock, Thread
import time


scenario = sys.argv[1]
token = os.environ["RPC_TEST_TOKEN"]
counts, jobs, lock = Counter(), {}, Lock()
denied = {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}
prefix = "/api/internal/memory/proposals/"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, body, status=200, *, raw=None, extra=None):
        data = json.dumps(body, ensure_ascii=False).encode() if raw is None else raw
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + token:
            self.send({"error": "runtime_auth_required"}, 401)
            return
        if not self.path.startswith(prefix):
            with lock:
                counts["forbidden_path"] += 1
            self.send({"error": "forbidden"}, 404)
            return
        operation = self.path[len(prefix):]
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = body["connection_id"]
            scope = tuple(body[name] for name in ("turn_id", "transcript_revision", "cancel_epoch"))
            assert body["version"] == 1
            common = {"version", "connection_id", "turn_id", "transcript_revision", "cancel_epoch"}
            extras = {"snapshot": {"query", "session_id"},
                      "start": {"snapshot_id", "messages", "tools_required"},
                      "confirm": {"snapshot_id", "query", "messages", "tools_required",
                                  "formal_turn_id", "client_round_id", "session_id"},
                      "cancel": set(), "close": set()}
            assert set(body) == common | extras[operation]
            assert all(type(value) is int and 0 <= value < 2**63 for value in scope)
        except Exception:
            self.send({"error": "voice_proposal_request_invalid"}, 400)
            return
        with lock:
            counts[operation] += 1
        if operation == "snapshot":
            if scenario == "redirect":
                self.send({}, 302, extra={"Location": "http://127.0.0.1:1/must-not-follow"})
                return
            if scenario == "bad_json":
                self.send({}, raw=b'{"version":1,"version":1}')
                return
            if scenario == "chunked":
                self.send({}, extra={"Transfer-Encoding": "chunked"})
                return
            self.send({"version": 1, "state": "ready", "snapshot_id": "e" * 32,
                       "memory_context": ("忆" * 30000 if scenario == "large_context" else
                                          "合成记忆：偏好无糖茶；来源test-L0-1。"), "reason_code": None})
        elif operation == "start":
            assert isinstance(body["messages"][0], list) and body["messages"][0][0] == "system"
            assert all(row[0] != "system" for row in body["messages"][1:])
            if body["tools_required"]:
                self.send({"version": 1, "state": "miss", "reason_code": "tools_required"})
                return
            with lock:
                jobs[key] = (scope, body["messages"])
                counts["preparing"] += 1
            if scenario == "slow_start":
                time.sleep(.4)
            if scenario == "disconnect_start":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            value = {"version": 1, "state": "preparing", "reason_code": None}
            if scenario == "leak_start":
                value["text"] = "不应提前送出的合成回答"
            self.send(value)
        elif operation == "confirm":
            if scenario in {"slow_confirm", "epoch_race"}:
                time.sleep(.25)
            with lock:
                current = jobs.get(key)
            matches = current == (scope, body["messages"]) and body["query"] == "完整合成问题"
            if scenario == "bad_confirm":
                self.send({"version": 1, "state": "miss", "text": "不应返回的合成回答", "reason_code": "miss"})
                return
            self.send({"version": 1, "state": "adopted" if matches else "miss",
                       "text": "合成有效回答" if matches else None, "reason_code": None if matches else "changed"})
        elif operation in {"cancel", "close"}:
            closed = scenario != "closing"
            if closed:
                with lock:
                    jobs.pop(key, None)
            self.send({"version": 1, "state": ("cancelled" if operation == "cancel" else "closed") if closed else "closing",
                       "owned_upstream_exited": closed, "provider_compute_stopped": scenario == "bad_ack"})
        else:
            self.send({"error": "not_allowed"}, 404)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server.daemon_threads = True
assert server.server_port not in denied
print(json.dumps({"port": server.server_port}), flush=True)


def stop():
    sys.stdin.readline()
    server.shutdown()


Thread(target=stop, daemon=True).start()
server.serve_forever(poll_interval=.01)
server.server_close()
print(json.dumps({"counts": dict(counts), "active": len(jobs)}), flush=True)
