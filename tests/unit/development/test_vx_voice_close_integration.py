"""V 等待取消与 X 退场工作者跟踪的组合；不绑定端口、不调用模型或 TTS。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('close_fails', [False, True])
def test_waiting_cancel_survives_control_close_wrapper_and_tracks_workers(monkeypatch, close_fails):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi'))
    import control_http
    import voice_latency
    from aiohttp import web

    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(release.wait, 3)
    cancelled, seen, calls = [], [], []
    waiting = SimpleNamespace(cancel=lambda: cancelled.append('waiting_cancelled'))

    class Connection:
        def chat(self, query, depth=0):
            raise AssertionError('This test must not start a conversation')

        async def handle_connection(self, ws):
            raise AssertionError('This test must not open a device connection')

        async def close(self):
            calls.append('original_close')
            assert cancelled == ['waiting_cancelled']
            if close_fails:
                raise RuntimeError('synthetic close failure')
            pool.shutdown(wait=False)
            self.executor = None

    class Site:
        def __init__(self, runner, host, port):
            assert (host, port) == ('127.0.0.1', 8766)

        async def start(self):
            pass  # 只验证包装组合；绝不打开日用控制端口。

    create_app = control_http.create_app

    def capture(control, token):
        seen.append(control)
        return create_app(control, token)

    monkeypatch.setattr(control_http, 'create_app', capture)
    monkeypatch.setattr(control_http, 'ensure_token', lambda: 'b' * 64)
    monkeypatch.setattr(web, 'TCPSite', Site)
    connection = Connection()
    connection.executor = pool
    connection.tts = None
    connection._longmemory_waiting = waiting

    class Server:
        config = {'Memory': {'LongMemory': {'allowed_device_id': 'synthetic-device'}}}

        async def _handle_connection(self, websocket):
            raise AssertionError('No connection may be accepted in this test')

        async def start(self):
            try:
                await connection.close()
            except RuntimeError:
                assert close_fails
            assert calls == ['original_close'] and cancelled == ['waiting_cancelled']
            control = seen[0]
            assert pool in control._network_retiring
            assert control_http.background_idle(control) is False

    # 与正式管线一致：先装 V 计时/close，再在服务器启动时装 X 控制包装。
    voice_latency.install_voice_latency(Connection)
    original_close = Connection.close
    control_http.install_control_server(Server, Connection)
    try:
        asyncio.run(Server().start())
        assert Connection.close is original_close  # 控制服务器退出恢复内层 V 包装。
    finally:
        release.set()
        future.result(timeout=1)
        pool.shutdown(wait=True)
    assert control_http.background_idle(seen[0]) is True
