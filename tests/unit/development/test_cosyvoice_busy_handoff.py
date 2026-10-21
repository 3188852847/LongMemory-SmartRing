"""仅明确无生成的503 busy可短等重试；其他故障与取消不重放。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
from cosyvoice_streaming import _open_stream, _SpeechCancelled


@pytest.fixture
def server():
    state = {"calls": 0, "responses": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["calls"] += 1
            code, body = state["responses"].pop(0) if state["responses"] else (503, {"error": "busy"})
            payload = json.dumps(body).encode() if isinstance(body, dict) else body
            self.send_response(code)
            self.send_header("Content-Type", "application/json" if code != 200 else "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    state["url"] = f"http://127.0.0.1:{http.server_address[1]}/v1/audio/stream"
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        worker.join(2)


def open_request(server, cancelled=lambda: False):
    return _open_stream(server["url"], json={"input": "synthetic"}, timeout=(1, 1),
                        headers={}, cancelled=cancelled)


def test_busy_then_success_retries_only_before_any_synthesis_response(server):
    server["responses"] = [(503, {"error": "busy"}), (503, {"error": "busy"}), (200, b"result")]
    with open_request(server) as response:
        assert response.raw.read() == b"result"
    assert server["calls"] == 3


@pytest.mark.parametrize("code,body", [(500, {"error": "busy"}), (503, {"error": "requires_restart"}),
                                        (503, {"error": "busy", "extra": True})])
def test_other_failures_never_retry(server, code, body):
    server["responses"] = [(code, body)]
    with pytest.raises(RuntimeError, match="http_rejected"):
        with open_request(server):
            pytest.fail("rejected response yielded")
    assert server["calls"] == 1


def test_busy_wait_is_bounded_and_next_cancellation_prevents_another_request(server):
    with pytest.raises(_SpeechCancelled):
        with open_request(server, lambda: server["calls"] > 0):
            pytest.fail("cancelled response yielded")
    assert server["calls"] == 1
    server["calls"] = 0
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="http_rejected"):
        with open_request(server):
            pytest.fail("busy response yielded")
    assert .35 <= time.monotonic() - started < 1.0
    assert 2 <= server["calls"] <= 24
