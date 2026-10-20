"""真实AF宿主/网关与独立3.10客户端之间的测试HTTP薄封装。

冻结源码由父测试从本地Git对象装到AE临时目录；Runtime是AF的合成fresh/锁替身。
不是AI正式路由，不接个人库/真实学校，不复制宿主或密钥到语音进程。
"""

import asyncio
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import sys
from threading import Lock, Thread


stage = Path(os.environ["RPC_REAL_HOST_ROOT"]).resolve()
sys.path[:0] = [str(stage / "src"), str(stage / "tests/unit/application"), str(stage / "tests/unit/methods")]
import longmemory
assert Path(longmemory.__file__).resolve().is_relative_to(stage / "src")
from longmemory.application.voice_proposals import VoiceProposalHost
import test_voice_proposals as fixtures


fixtures.QUERY, fixtures.SESSION = "完整合成问题", "c" * 32
scenario, token = sys.argv[1], os.environ["RPC_TEST_TOKEN"]
denied = {8766, 8767, 8768, 8000, 8003, 18000, 18003, 18767, 18768, 18769, 18770}
counts, counts_lock = Counter(), Lock()


class MultiChannelRuntime(fixtures.Runtime):
    """同一合成formal投影：画像1+fact4+intent1，防止小库掩盖截断。"""

    def __init__(self, gateway):
        super().__init__(gateway)
        self.items = [
            {"memory_id": "synthetic-profile", "content": "合成画像", "layer": "l0_basic_info", "channel": "profile"},
            *[{"memory_id": "synthetic-fact-" + str(index), "content": "合成事实" + str(index),
               "layer": "l2_fact", "channel": "normal"} for index in range(1, 5)],
            {"memory_id": "synthetic-intent", "content": "合成意图", "layer": "l7_intention", "channel": "proactive"},
        ]
        for row in self.items:
            row["source_event_ids"] = [row["memory_id"] + "-source"]
            row["evidence_memory_ids"] = [row["memory_id"]]

    def candidate_memory_snapshot(self, query, *, limit=5):
        result = super().candidate_memory_snapshot(query, limit=limit)
        result["engine"]["items"] = deepcopy(self.items)
        result["engine"]["memory_digest"] = sha256(json.dumps(self.items, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return result

    def claim_candidate_memory(self, receipt, **kwargs):
        with self.lock:
            if receipt["engine"]["items"] != self.items:
                return None
            return super().claim_candidate_memory(receipt, **kwargs)


async def main():
    raw = fixtures.complete_wire()
    plan = {"body": raw}
    if scenario in {"real_host_headers_cancel", "real_host_revised_cleanup", "real_host_new_turn_cleanup"}:
        plan["mode"] = "wait_headers"
    elif scenario == "real_host_body_cancel":
        plan["split"] = raw.index(b"\n\n") + 2
    with fixtures.gateway(stage, [plan]) as (gateway, ledger, received, first, release):
        runtime = MultiChannelRuntime(gateway)
        if scenario == "real_host_fresh_miss":
            runtime.formal_valid = False
        host = VoiceProposalHost(lambda: runtime, enabled=True)
        loop = asyncio.get_running_loop()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def send(self, body, status=200):
                data = json.dumps(body, ensure_ascii=False).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def do_POST(self):
                if (self.headers.get("Authorization") != "Bearer " + token
                        or self.headers.get("Host") != "127.0.0.1:" + str(server.server_port)):
                    self.send({"error": "runtime_auth_required"}, 401)
                    return
                prefix = "/api/internal/memory/proposals/"
                operation = self.path[len(prefix):] if self.path.startswith(prefix) else ""
                if operation not in {"snapshot", "start", "confirm", "cancel", "close"}:
                    self.send({"error": "not_allowed"}, 404)
                    return
                with counts_lock:
                    counts[operation] += 1
                try:
                    size = int(self.headers["Content-Length"])
                    if not 0 < size <= 192 * 1024:
                        raise ValueError
                    body = json.loads(self.rfile.read(size))
                    if operation == "cancel" and scenario in {"real_host_headers_cancel", "real_host_body_cancel"}:
                        if not first.wait(1):
                            raise RuntimeError
                    if (operation == "snapshot" and body["cancel_epoch"] == 1
                            and scenario in {"real_host_revised_cleanup", "real_host_new_turn_cleanup"}):
                        if not first.wait(1):
                            raise RuntimeError
                    if operation == "confirm" and scenario == "real_host_source_miss":
                        runtime.items[0]["source_event_ids"] = ["synthetic-changed-source"]
                    result = asyncio.run_coroutine_threadsafe(getattr(host, operation)(body), loop).result(timeout=3)
                except ValueError:
                    self.send({"error": "voice_proposal_request_invalid"}, 400)
                except Exception:
                    self.send({"error": "voice_proposal_rejected"}, 409)
                else:
                    self.send(result)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        assert server.server_port not in denied
        thread = Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        print(json.dumps({"port": server.server_port}), flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(1)
        closed = await host.aclose()
        release.set()
        status = ledger.status()
        wire = json.loads(received[0]["body"]) if received else None
        system = "" if wire is None else wire["messages"][0]["content"]
        print(json.dumps({"counts": dict(counts), "active": int(not closed["closed"]),
                          "attempt_count": status["attempt_count"], "unknown": status["unknown_or_inflight"],
                          "claimed": runtime.claimed, "candidate_handles": len(gateway._candidate_handles),
                          "memory_items": len(runtime.items),
                          "context_items_sent": sum(row["content"] in system for row in runtime.items),
                          "host_closed": closed["closed"], "provider_compute_stopped": False}), flush=True)


asyncio.run(main())
