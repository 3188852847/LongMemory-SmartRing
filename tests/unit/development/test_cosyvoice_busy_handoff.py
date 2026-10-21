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
from types import SimpleNamespace
from voice_interruption import OutputLease


@pytest.fixture
def server():
    state = {"calls": 0, "responses": [], "header_delays": {}, "body_delays": {}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            state["calls"] += 1
            call = state["calls"]
            code, body = state["responses"].pop(0) if state["responses"] else (503, {"error": "busy"})
            payload = json.dumps(body).encode() if isinstance(body, dict) else body
            time.sleep(state["header_delays"].get(call, 0))
            self.send_response(code)
            self.send_header("Content-Type", "application/json" if code != 200 else "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            time.sleep(state["body_delays"].get(call, 0))
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端预算耗尽/取消，测试服务不把预期断开打印成异常。
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


def test_retry_headers_share_busy_deadline_and_never_admit_a_third_attempt(server):
    server['responses'] = [(503, {'error':'busy'}), (200, b'late')]
    server['header_delays'] = {2: .8}
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='http_rejected'):
        with open_request(server):
            pytest.fail('late admission yielded')
    assert .35 <= time.monotonic() - started < .7
    assert server['calls'] == 2


def test_first_request_timeout_and_admitted_generation_are_not_busy_budget(server):
    server['responses'] = [(503, {'error':'busy'}), (200, b'complete')]
    server['header_delays'] = {1: .45}
    server['body_delays'] = {2: .5}
    with open_request(server) as response:
        assert response.raw.read() == b'complete'
    assert server['calls'] == 2


@pytest.mark.parametrize('reason', ['cancel', 'new_turn', 'close'])
def test_revocation_during_retry_headers_closes_owned_socket_without_retry(server, reason):
    server['responses'] = [(503, {'error':'busy'}), (200, b'late')]
    server['header_delays'] = {2: .8}
    lease = OutputLease(SimpleNamespace(sentence_id='synthetic'), 'synthetic')
    def revoke():
        while server['calls'] < 2:
            time.sleep(.002)
        lease.state.revoke({'cancel':'upstream_abort_revoked', 'new_turn':'asr_handoff_revoked',
                            'close':'connection_closed'}[reason])
        if reason == 'close':
            lease.state.closed = True
    worker = threading.Thread(target=revoke, daemon=True); worker.start()
    started = time.monotonic()
    with pytest.raises(_SpeechCancelled):
        with open_request(server, lambda: not lease.current()):
            pytest.fail(reason + ' yielded')
    worker.join(1)
    assert time.monotonic() - started < .5 and server['calls'] == 2


def test_error_after_200_never_replays_generation(server):
    server['responses'] = [(200, b'complete')]
    with pytest.raises(ValueError, match='synthetic_body_failure'):
        with open_request(server):
            raise ValueError('synthetic_body_failure')
    assert server['calls'] == 1
