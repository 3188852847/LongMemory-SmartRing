"""真实回环HTTP验证网络静默租约；仅独立随机端口，不连接日用服务。"""

import asyncio
from pathlib import Path
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from longmemory.entrypoints.api.network_maintenance import NetworkMaintenance, PATH, owned_runtime_idle
from longmemory.entrypoints.api.security import Sessions, security_middleware


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_console_lease_auth_busy_gate_release_and_expiry():
    async def run():
        port, instance, token = free_port(), 'a' * 48, 'b' * 64
        now, background = [0.0], [True]
        gate = NetworkMaintenance(instance, clock=lambda: now[0])
        gate.supported = True
        gate.idle_checks.append(lambda: background[0])
        app = web.Application(middlewares=[security_middleware(f'127.0.0.1:{port}', Sessions(), token), gate.middleware])
        app.router.add_post(PATH, gate.handle)
        entered, release = asyncio.Event(), asyncio.Event()

        async def work(_request):
            entered.set()
            await release.wait()
            return web.Response(text='synthetic complete')

        app.router.add_get('/synthetic-work', work)
        async def health(_request):
            return web.Response(text='ok')
        app.router.add_get('/synthetic-health', health)
        client = TestClient(TestServer(app, host='127.0.0.1', port=port))
        await client.start_server()
        headers = {'Authorization': 'Bearer ' + token}
        body = {'instance': instance, 'draining': True}
        try:
            assert (await client.post(PATH, json=body)).status == 401
            assert (await client.post(PATH, json=body, headers={**headers, 'Origin': f'http://127.0.0.1:{port}'})).status == 403
            assert (await client.post(PATH, json={**body, 'instance': 'wrong'}, headers=headers)).status == 409
            task = asyncio.create_task(client.get('/synthetic-work'))
            await entered.wait()
            assert (await client.post(PATH, json=body, headers=headers)).status == 409
            release.set()
            assert (await task).status == 200
            background[0] = False
            assert (await client.post(PATH, json=body, headers=headers)).status == 409
            background[0] = True
            assert (await client.post(PATH, json=body, headers=headers)).status == 200
            assert (await client.get('/synthetic-health')).status == 503
            assert (await client.post(PATH, json={**body, 'draining': False}, headers=headers)).status == 200
            assert (await client.get('/synthetic-health')).status == 200
            assert (await client.post(PATH, json=body, headers=headers)).status == 200
            now[0] += 61
            assert (await client.get('/synthetic-health')).status == 200
            gate.supported = False
            assert (await client.post(PATH, json=body, headers=headers)).status == 409
        finally:
            await client.close()
    asyncio.run(run())


def test_voice_lease_rejects_connected_incoming_or_control_operation(monkeypatch):
    directory = Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi'
    monkeypatch.syspath_prepend(str(directory))
    from control_http import create_app
    monkeypatch.setenv('LONGMEMORY_LAUNCHER_INSTANCE', 'a' * 48)

    async def run():
        port, token = free_port(), 'b' * 64
        control = SimpleNamespace(connections={}, operation_lock=asyncio.Lock())
        client = TestClient(TestServer(create_app(control, token, port), host='127.0.0.1', port=port))
        await client.start_server()
        headers = {'Authorization': 'Bearer ' + token}
        body = {'instance': 'a' * 48, 'draining': True}
        try:
            assert (await client.post('/api/network-maintenance', json=body)).status == 401
            control.connections['synthetic-device'] = object()
            assert (await client.post('/api/network-maintenance', json=body, headers=headers)).status == 409
            control.connections.clear()
            control._network_incoming = 1
            assert (await client.post('/api/network-maintenance', json=body, headers=headers)).status == 409
            control._network_incoming = 0
            await control.operation_lock.acquire()
            assert (await client.post('/api/network-maintenance', json=body, headers=headers)).status == 409
            control.operation_lock.release()
            assert (await client.post('/api/network-maintenance', json=body, headers=headers)).status == 200
            assert control._network_drain_until > 0
            assert (await client.post('/api/network-maintenance', json={**body, 'draining': False}, headers=headers)).status == 200
            assert control._network_drain_until == 0
        finally:
            await client.close()
    asyncio.run(run())


def test_disconnected_request_keeps_actual_background_work_busy():
    async def run():
        gate = NetworkMaintenance('synthetic')
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(timeout=3)
        async def handler(_request):
            await asyncio.to_thread(work)
            return web.Response()
        wrapper = asyncio.create_task(gate.middleware(SimpleNamespace(path='/synthetic-work'), handler))
        await asyncio.to_thread(entered.wait, 1)
        assert entered.is_set() and gate.active == 1
        wrapper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wrapper
        assert gate.active == 1 and gate.pending
        release.set()
        await asyncio.gather(*tuple(gate.pending))
        await asyncio.sleep(0)
        assert gate.active == 0 and not gate.pending
    asyncio.run(run())


def test_voice_disconnect_workers_must_finish_before_network_restart(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi'))
    from control_http import remember_background, background_idle
    control = SimpleNamespace(_network_retiring=[], _network_unknown_background=False)
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(release.wait, 3)
    thread = threading.Thread(target=release.wait, args=(3,))
    thread.start()
    conn = SimpleNamespace(executor=pool, tts=SimpleNamespace(tts_priority_thread=thread))
    try:
        remember_background(control, conn)
        pool.shutdown(wait=False)
        conn.executor = None  # 固定上游close的实际行为，不能据此认定任务结束。
        assert background_idle(control) is False
        release.set()
        future.result(timeout=1)
        pool.shutdown(wait=True)
        thread.join(timeout=1)
        assert background_idle(control) is True and control._network_retiring == []
        remember_background(control, SimpleNamespace(executor=object()))
        assert background_idle(control) is False and control._network_retiring == []
    finally:
        release.set()
        pool.shutdown(wait=True)
        thread.join(timeout=1)


def test_runtime_and_gateway_inflight_or_deferred_work_prevents_quiescence():
    from threading import Lock, RLock
    from concurrent.futures import Future
    gateway = SimpleNamespace(_connections_lock=Lock(), _closed=False, _downstreams=set(), _streams=set())
    runtime = SimpleNamespace(_lock=RLock(), _closed=False, _closing=False, _deferred_futures=set(),
                              _model_service=SimpleNamespace(gateway=gateway, closed=False))
    assert owned_runtime_idle(runtime) is True
    gateway._downstreams.add('synthetic-active-handler')
    assert owned_runtime_idle(runtime) is False
    gateway._downstreams.clear()
    gateway._streams.add('synthetic-active-stream')
    assert owned_runtime_idle(runtime) is False
    gateway._streams.clear()
    future = Future()
    runtime._deferred_futures.add(future)
    assert owned_runtime_idle(runtime) is False
    future.set_result(None)
    assert owned_runtime_idle(runtime) is True
    with gateway._connections_lock:
        assert owned_runtime_idle(runtime) is False
    assert owned_runtime_idle(SimpleNamespace()) is False
