"""临时回环HTTP供应商验证复用、即时行流、边界、取消和零重试。"""

from collections import deque
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory import provider_transport as module
from longmemory.methods.hy_memory.provider_transport import PersistentProviderTransport


@contextmanager
def supplier(plans):
    plans = deque(plans)
    requests = []
    lock = Lock()
    first, release = Event(), Event()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        timeout = 2
        def log_message(self, *args): pass
        def do_POST(self):
            payload = self.rfile.read(int(self.headers['Content-Length']))
            with lock:
                requests.append({'connection': self.connection, 'path': self.path, 'body': payload,
                    'authorization': self.headers.get('Authorization'), 'cookie': self.headers.get('Cookie')})
                plan = plans.popleft() if plans else {'body': b'unexpected-extra-request'}
            mode = plan.get('mode')
            if mode == 'disconnect':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if mode == 'wait_headers':
                first.set()
                release.wait(3)
            body = plan.get('body', b'{}')
            self.send_response(plan.get('status', 200))
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Set-Cookie', 'synthetic=private; Path=/')
            if plan.get('status') == 302:
                self.send_header('Location', '/must-not-follow')
            self.end_headers()
            try:
                split = plan.get('split')
                if split is None:
                    self.wfile.write(body)
                    self.wfile.flush()
                else:
                    self.wfile.write(body[:split])
                    self.wfile.flush()
                    first.set()
                    release.wait(3)
                    self.wfile.write(body[split:])
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    assert server.server_port not in {8766, 8767, 8000, 8003, 18770}
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    settings = SimpleNamespace(base_url=f'http://127.0.0.1:{server.server_port}/v1',
        api_key='synthetic-private-credential', timeout_seconds=2, allow_http=True)
    transport = PersistentProviderTransport(settings)
    try:
        yield transport, requests, first, release
    finally:
        release.set()
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def test_no_startup_request_and_session_reuses_eof_connection_across_send_and_stream():
    with supplier([{'body': b'{"ok":1}'}, {'body': b'data: first\n\ndata: [DONE]\n\n'},
                   {'body': b'{"ok":2}'}]) as (transport, requests, _, __):
        assert transport._thread is None and transport._session is None and requests == []
        assert transport.send(b'{"stream":false}') == (200, b'{"ok":1}')
        thread, session = transport._thread, transport._session
        with transport.stream(b'{"stream":true}') as (status, lines):
            assert status == 200
            assert list(lines) == [b'data: first\n', b'\n', b'data: [DONE]\n', b'\n']
        assert transport.send(b'{}') == (200, b'{"ok":2}')
        assert transport._thread is thread and transport._session is session
        assert len({id(row['connection']) for row in requests}) == 1
        assert len(requests) == 3
        assert all(row['path'] == '/v1/chat/completions' for row in requests)
        assert all(row['cookie'] is None for row in requests)
        assert all(row['authorization'] == 'Bearer synthetic-private-credential' for row in requests)
        assert session.timeout.total is None and session.timeout.sock_read == 2 and session.timeout.sock_connect == 2
        assert session.connector._keepalive_timeout == 120


def test_first_line_arrives_before_provider_finishes():
    body = b'data: first\n\ndata: final\n\n'
    with supplier([{'body': body, 'split': 13}]) as (transport, requests, first, release):
        with transport.stream(b'{}') as (status, lines):
            assert status == 200 and next(lines) == b'data: first\n'
            assert first.wait(1) and not release.is_set()
            release.set()
            assert b'data: final\n' in list(lines)
        assert len(requests) == 1


def test_abandoned_unread_stream_is_closed_and_next_request_uses_clean_connection():
    body = b'data: first\n\ndata: stale-tail\n\n'
    with supplier([{'body': body, 'split': 13}, {'body': b'fresh'}]) as (transport, requests, first, release):
        with transport.stream(b'{}') as (_, lines):
            assert next(lines) == b'data: first\n'
            assert first.wait(1)
        assert transport.send(b'{}') == (200, b'fresh')
        assert len(requests) == 2
        assert requests[0]['connection'] is not requests[1]['connection']
        release.set()


@pytest.mark.parametrize('streaming', [False, True])
def test_redirect_response_does_not_trigger_followup_or_retry(streaming):
    with supplier([{'status': 302, 'body': b''}]) as (transport, requests, _, __):
        if streaming:
            with transport.stream(b'{}') as (status, lines):
                assert status == 302 and list(lines) == []
        else:
            assert transport.send(b'{}') == (302, b'')
        assert len(requests) == 1


@pytest.mark.parametrize('streaming', [False, True])
def test_connection_failure_is_one_post_and_sanitized_then_next_round_works(streaming):
    with supplier([{'mode': 'disconnect'}, {'body': b'fresh'}]) as (transport, requests, _, __):
        with pytest.raises(OSError, match='^provider_stream_interrupted$') as error:
            if streaming:
                with transport.stream(b'synthetic-private-question') as (_, lines):
                    list(lines)
            else:
                transport.send(b'synthetic-private-question')
        assert 'private' not in str(error.value)
        assert len(requests) == 1
        assert transport.send(b'{}') == (200, b'fresh')
        assert len(requests) == 2


@pytest.mark.parametrize('streaming', [False, True])
def test_failed_post_on_a_previously_reused_connection_is_not_retried(streaming):
    with supplier([{'body': b'warm'}, {'mode': 'disconnect'}, {'body': b'explicit-next'}]) as (transport, requests, _, __):
        assert transport.send(b'{}') == (200, b'warm')
        with pytest.raises(OSError, match='^provider_stream_interrupted$'):
            if streaming:
                with transport.stream(b'{}') as (_, lines):
                    list(lines)
            else:
                transport.send(b'{}')
        assert len(requests) == 2
        assert requests[0]['connection'] is requests[1]['connection']
        assert transport.send(b'{}') == (200, b'explicit-next')
        assert len(requests) == 3


def test_send_enforces_body_limit_and_exact_boundary_without_retry(monkeypatch):
    monkeypatch.setattr(module, 'MAX_BODY', 8)
    with supplier([{'body': b'12345678'}, {'body': b'123456789'}, {'body': b'ok'}]) as (transport, requests, _, __):
        assert transport.send(b'{}') == (200, b'12345678')
        with pytest.raises(ValueError, match='^provider_stream_invalid$'):
            transport.send(b'{}')
        assert transport.send(b'{}') == (200, b'ok')
        assert len(requests) == 3


def test_send_waits_for_actual_eof_instead_of_returning_a_short_read():
    with supplier([{'body': b'complete-body', 'split': 3}]) as (transport, requests, first, release):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(transport.send, b'{}')
            assert first.wait(1) and not future.done()
            release.set()
            assert future.result(timeout=1) == (200, b'complete-body')
        assert len(requests) == 1


@pytest.mark.parametrize('body,limit', [(b'12345678\n', 'MAX_LINE'), (b'a\nb\nc\nd\ne\n', 'MAX_STREAM')])
def test_stream_line_and_total_limits_fail_without_retry(monkeypatch, body, limit):
    monkeypatch.setattr(module, limit, 8)
    with supplier([{'body': body}, {'body': b'ok'}]) as (transport, requests, _, __):
        with pytest.raises(ValueError, match='^provider_stream_invalid$'):
            with transport.stream(b'{}') as (_, lines):
                list(lines)
        assert transport.send(b'{}') == (200, b'ok')
        assert len(requests) == 2


@pytest.mark.parametrize('streaming', [False, True])
def test_close_interrupts_headers_wait_and_forbids_new_requests(streaming):
    with supplier([{'mode': 'wait_headers'}]) as (transport, requests, first, release):
        def request():
            if streaming:
                with transport.stream(b'{}') as (_, lines):
                    list(lines)
            else:
                transport.send(b'{}')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(request)
            assert first.wait(1)
            transport.close()
            with pytest.raises(OSError, match='^provider_stream_interrupted$'):
                future.result(timeout=1)
        assert not transport._thread.is_alive() and transport._session.closed
        assert len(requests) == 1
        with pytest.raises(ValueError, match='^provider_transport_closed$'):
            transport.send(b'{}')
        with pytest.raises(ValueError, match='^provider_transport_closed$'):
            with transport.stream(b'{}'):
                pass
        release.set()


def test_close_before_first_request_is_inert_and_idempotent():
    settings = SimpleNamespace(base_url='https://synthetic.invalid/v1', api_key='not-real',
                               timeout_seconds=1, allow_http=False)
    transport = PersistentProviderTransport(settings)
    transport.close()
    transport.close()
    assert transport._thread is None and transport._session is None
    with pytest.raises(ValueError, match='provider_transport_closed'):
        transport.send(b'{}')


def test_close_interrupts_an_active_body_reader_and_reaps_loop():
    body = b'data: first\n\ndata: blocked-tail\n\n'
    with supplier([{'body': body, 'split': 13}]) as (transport, requests, first, release):
        blocked = Event()
        def read():
            with transport.stream(b'{}') as (_, lines):
                assert next(lines) == b'data: first\n'
                assert first.wait(1)
                assert next(lines) == b'\n'
                blocked.set()
                return next(lines)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(read)
            assert blocked.wait(1)
            transport.close()
            with pytest.raises(OSError, match='^provider_stream_interrupted$'):
                future.result(timeout=1)
        assert not transport._thread.is_alive() and transport._session.closed
        assert len(requests) == 1
        release.set()


def test_abandoning_full_packet_queue_is_cancellable_and_next_round_is_clean():
    with supplier([{'body': b'data: old\n' * 200}, {'body': b'fresh'}]) as (transport, requests, _, __):
        with transport.stream(b'{}') as (status, lines):
            assert status == 200
            # 消费者不读：producer最多保留32行，退出必须取消背压等待。
        assert transport.send(b'{}') == (200, b'fresh')
        assert len(requests) == 2


def test_shutdown_failure_is_explicit_sanitized_and_repeatable(monkeypatch):
    with supplier([{'body': b'ok'}]) as (transport, _, __, ___):
        transport.send(b'{}')
        original = transport._shutdown
        async def failed_shutdown():
            await original()
            raise RuntimeError('synthetic-private-close-detail')
        monkeypatch.setattr(transport, '_shutdown', failed_shutdown)
        try:
            for _ in range(2):
                with pytest.raises(RuntimeError, match='^provider_transport_close_unconfirmed$'):
                    transport.close()
            assert not transport._thread.is_alive()
        finally:
            # 实际session和线程已关闭；仅让fixture的幂等收尾不重复抛故障。
            transport._close_failed = False


def test_global_close_racing_per_stream_cleanup_does_not_report_a_false_failure(monkeypatch):
    with supplier([{'body': b'data: done\n'}]) as (transport, _, __, ___):
        entered = Event()
        async def waiting_cleanup(state):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(transport, '_cancel_stream', waiting_cleanup)
        def consume():
            with transport.stream(b'{}') as (_, lines):
                assert list(lines) == [b'data: done\n']
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(consume)
            assert entered.wait(1)
            transport.close()
            future.result(timeout=1)
        assert not transport._thread.is_alive()


@pytest.mark.parametrize('url,allow_http', [('http://synthetic.invalid/v1', False),
    ('ftp://synthetic.invalid', True), ('https://name:secret@synthetic.invalid', True),
    ('https://synthetic.invalid/v1?secret=value', True), ('https://synthetic.invalid/#fragment', True)])
def test_unapproved_or_ambiguous_endpoint_is_rejected_without_thread(url, allow_http):
    settings = SimpleNamespace(base_url=url, api_key='synthetic', timeout_seconds=1, allow_http=allow_http)
    with pytest.raises(ValueError, match='^provider_transport_not_authorized$'):
        PersistentProviderTransport(settings)


def test_distinct_instances_never_share_session_connection_or_credentials():
    with supplier([{'body': b'one'}, {'body': b'two'}]) as (first, requests, _, __):
        settings = SimpleNamespace(base_url=first._url.removesuffix('/chat/completions'),
            api_key='other-synthetic-credential', timeout_seconds=2, allow_http=True)
        second = PersistentProviderTransport(settings)
        try:
            assert first.send(b'{}') == (200, b'one')
            assert second.send(b'{}') == (200, b'two')
            assert first._session is not second._session
            assert requests[0]['connection'] is not requests[1]['connection']
            assert requests[0]['authorization'] != requests[1]['authorization']
        finally:
            second.close()


def test_gateway_answer_projection_over_real_persistent_json_and_fragmented_sse(tmp_path):
    from io import BytesIO
    from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
    from longmemory.infrastructure.config.settings import ModelSettings
    from longmemory.methods.hy_memory.model_gateway import ModelGateway
    usage = {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}
    plain = {'choices': [{'message': {'role': 'assistant', 'reasoning_content': 'synthetic-hidden',
        'content': '<think>合成推理</think>最终答案'}}], 'usage': usage}
    packets = [{'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '<thi'}}]},
        {'choices': [{'index': 0, 'delta': {'content': 'nk>合成推理</th', 'reasoning_content': 'synthetic-hidden'}}]},
        {'choices': [{'index': 0, 'delta': {'content': 'ink>最终答案'}, 'finish_reason': 'stop'}]},
        {'choices': [], 'usage': usage}]
    body = b''.join(b'data: ' + json.dumps(value, ensure_ascii=False).encode() + b'\r\n\r\n' for value in packets)
    body += b'data: [DONE]\r\n\r\n'
    split = body.index('合成推理'.encode()) + 1  # 实际HTTP读取在UTF-8多字节中间截断。
    with supplier([{'body': json.dumps(plain).encode()}, {'body': body, 'split': split}]) as (transport, requests, first, release):
        settings = ModelSettings(provider='openai_compatible', model='synthetic-campus',
            base_url=transport._url.removesuffix('/chat/completions'), api_key='synthetic-private-credential',
            allow_http=True, timeout_seconds=2)
        budget = FreeCampusCalls(tmp_path / 'synthetic-free.sqlite3', proof={'request_model': settings.model}, create=True)
        gateway = ModelGateway(settings=settings, budget=budget, encoder=SimpleNamespace(identity='f' * 64), free_policy_verified=True)
        class Handler:
            def __init__(self): self.wfile = BytesIO()
            def send_response(self, status): assert status == 200
            def send_header(self, *args): pass
            def end_headers(self): pass
        handler = Handler()
        try:
            request = {'model': settings.model, 'max_tokens': 512, 'messages': [], 'stream': False}
            status, result = gateway.complete('answer', request)
            assert status == 200 and result['choices'][0]['message'] == {'role': 'assistant', 'content': '最终答案'}
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(gateway.stream, {**request, 'stream': True}, handler)
                assert first.wait(1) and not future.done()
                assert b'synthetic-hidden' not in handler.wfile.getvalue()
                release.set()
                future.result(timeout=2)
            received = [json.loads(line[5:]) for line in handler.wfile.getvalue().splitlines()
                if line.startswith(b'data:') and line[5:].strip() != b'[DONE]']
            text = ''.join(choice['delta'].get('content') or '' for value in received for choice in value.get('choices', []))
            assert text == '最终答案' and received[-1]['usage'] == usage
            assert b'synthetic-hidden' not in handler.wfile.getvalue() and handler.wfile.getvalue().endswith(b'[DONE]\n\n')
            assert len(requests) == 2 and requests[0]['connection'] is requests[1]['connection']
            assert budget.status()['attempt_count'] == 2 and budget.status()['unknown_or_inflight'] == 0
        finally:
            release.set()
            gateway.close()
        assert not gateway._provider_transport._thread.is_alive()
