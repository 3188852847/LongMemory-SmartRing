"""候选实际owned连接池/账本组合；只使用随机回环端口与合成材料。"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
from threading import Event

import pytest

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.candidate_response import DENIED_PORTS
from longmemory.methods.hy_memory import candidate_response as candidate_module
from test_hy_provider_transport import supplier


USAGE = {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}


def wire(*packets, done=True):
    result = b''.join(b'data: '+json.dumps(packet, ensure_ascii=False).encode()+b'\n\n' for packet in packets)
    return result + (b'data: [DONE]\n\n' if done else b'')


def delta(text=None, **extra):
    return {'choices': [{'index': 0, 'delta': dict({'content': text} if text is not None else {}, **extra)}]}


def complete_wire(*, usage=USAGE, finish='stop', done=True):
    return wire(delta(reasoning_content='SYNTHETIC_INTERNAL'), delta('<thi'), delta('nk>hidden</think>合成回答'),
        {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]},
        *([{'choices': [], 'usage': usage}] if usage is not None else []), done=done)


def body(model='DeepSeek-V4-Flash'):
    return {'model': model, 'messages': [{'role': 'system', 'content': '合成角色与已冻结规则'},
        {'role': 'user', 'content': '合成记忆证据'}, {'role': 'assistant', 'content': '合成旧回答'},
        {'role': 'user', 'content': '合成当前问题'}], 'max_tokens': 256, 'stream': True,
        'stream_options': {'include_usage': True}, 'n': 1, 'tool_choice': 'none', 'thinking': {'type': 'disabled'}}


@contextmanager
def gateway(tmp_path, plans, *, model='DeepSeek-V4-Flash'):
    with supplier(plans) as (transport, received, first, release):
        url = transport._url.removesuffix('/chat/completions')
        assert int(url.split(':')[2].split('/')[0]) not in DENIED_PORTS
        settings = ModelSettings(provider='openai_compatible', base_url=url, api_key='synthetic-private-credential',
            model=model, allow_http=True, timeout_seconds=2)
        proof = {'version': 1, 'profile': 'campus', 'billing_mode': 'owner_confirmed_free',
            'personal_cost_micro_cny': 0, 'source': 'owner_confirmation', 'confirmed_date': '2026-10-19',
            'endpoint_sha256': sha256(url.encode()).hexdigest(), 'request_model': settings.model,
            'credential_sha256': sha256(settings.api_key.encode()).hexdigest(),
            'ledger_path': 'data/databases/synthetic-candidate.sqlite3'}
        ledger = FreeCampusCalls(tmp_path/'calls.sqlite3', proof=proof, create=True)
        server = ModelGateway(settings=settings, budget=ledger, encoder=object(), free_policy_verified=True)
        server._provider_transport.close()
        server._provider_transport = transport
        try:
            yield server, ledger, received, first, release
        finally:
            release.set()
            server.close()


async def consume(handle):
    async with handle as response:
        assert type(response.status) is int
        return b''.join([line async for line in response.content])


def records(ledger):
    with sqlite3.connect(ledger.path) as db:
        return db.execute('SELECT failure,done,forwarded,usage_seen FROM gateway_results').fetchall()


def test_binding_uses_precise_school_model_policy_pool_and_existing_budget(tmp_path):
    plain = json.dumps({'choices': [{'message': {'content': '合成正式回答'}}], 'usage': USAGE}).encode()
    with gateway(tmp_path, [{'body': plain}, {'body': complete_wire()}, {'body': plain}]) as (server, ledger, received, _, __):
        binding = server.candidate_response_binding()
        assert binding['model'] == 'DeepSeek-V4-Flash' and binding['campus_free_verified'] is True
        request = body(); original = deepcopy(request)
        normal = {'model': request['model'], 'messages': request['messages'], 'stream': False, 'max_tokens': 256}
        assert server.complete('answer', normal)[0] == 200
        session = server._provider_transport._session
        handle = binding['open_response'](request)
        assert len(received) == 1 and ledger.status()['attempt_count'] == 1
        async def run():
            output = await consume(handle)
            ack = await handle.wait_closed()
            assert ack == {'request_id': handle.request_id, 'owned_upstream_exited': True,
                'provider_compute_stopped': False, 'ledger_finalized': True, 'usage_settled': True}
            assert b'SYNTHETIC_INTERNAL' not in output and b'hidden' not in output
            assert '合成回答'.encode() in output and b'[DONE]' in output
        asyncio.run(run())
        assert request == original and json.loads(received[1]['body']) == request
        assert server._provider_transport._session is session
        assert server.complete('answer', normal)[0] == 200
        assert len({id(row['connection']) for row in received}) == 1 and len(received) == 3
        assert ledger.status()['attempt_count'] == 3 and ledger.status()['unknown_or_inflight'] == 0
        assert server.responses[1]['candidate'] and server.responses[1]['cache']['state'] == 'unknown'
        assert not server._streams and not server._candidate_handles and not server._paid_lock.locked()
        assert records(ledger)[1] == (None, 1, 0, 1)
        assert '合成当前问题' not in repr(server.responses) and 'SYNTHETIC_INTERNAL' not in repr(server.responses)


@pytest.mark.parametrize('change', ['model', 'endpoint', 'credential', 'free', 'ledger', 'unverified'])
def test_binding_rejects_unbound_or_mutated_policy_before_network(tmp_path, change):
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        if change == 'model': ledger.proof['request_model'] = 'other'
        elif change == 'endpoint': ledger.proof['endpoint_sha256'] = '0'*64
        elif change == 'credential': ledger.proof['credential_sha256'] = '0'*64
        elif change == 'free': ledger.proof['personal_cost_micro_cny'] = 1
        elif change == 'ledger':
            with sqlite3.connect(ledger.path) as db: db.execute("UPDATE policy SET body='{}'")
        else: server._free_policy_verified = False
        with pytest.raises(ValueError): server.candidate_response_binding()
        assert not received and ledger.status()['attempt_count'] == 0


@pytest.mark.parametrize('change', ['tools', 'tokens', 'model', 'n', 'thinking', 'stream', 'tail_system', 'tool_history'])
def test_invalid_payload_cannot_escape_bounded_frozen_messages(tmp_path, change):
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        request = body()
        if change == 'tools': request['tools'] = []
        elif change == 'tokens': request['max_tokens'] = 257
        elif change == 'model': request['model'] = 'deepseek-v4-flash'
        elif change == 'n': request['n'] = True
        elif change == 'thinking': request['thinking'] = {'type': 'enabled'}
        elif change == 'stream': request['stream'] = False
        elif change == 'tail_system': request['messages'].append({'role': 'system', 'content': '尾规则'})
        else: request['messages'][1] = {'role': 'tool', 'content': '工具结果'}
        with pytest.raises(ValueError): server.open_candidate_response(request)
        assert not received and ledger.status()['attempt_count'] == 0


@pytest.mark.parametrize('raw', [
    complete_wire(usage=None), complete_wire(finish='length'), complete_wire(done=False),
    complete_wire(usage={**USAGE, 'completion_tokens': True}),
    complete_wire(usage={**USAGE, 'completion_tokens': 257, 'total_tokens': 267}),
    wire(delta('片段'), delta(tool_calls=[{'function': {'name': 'mutate'}}])),
    wire(delta(function_call={'name': 'mutate'})), wire(delta('<think>未结束')),
    wire({'error': {'message': 'SYNTHETIC_PRIVATE_ERROR'}}), b'data: invalid-json\n\n',
])
def test_invalid_incomplete_or_tool_response_retains_unknown_and_no_retry(tmp_path, raw):
    with gateway(tmp_path, [{'body': raw}]) as (server, ledger, received, _, __):
        handle = server.open_candidate_response(body())
        with pytest.raises(ValueError, match='^candidate_stream_invalid$'):
            asyncio.run(consume(handle))
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 1
        assert not server._paid_lock.locked() and not server._streams
        assert records(ledger)[0][:3] == ('stream_invalid', 0, 0)
        assert 'SYNTHETIC_PRIVATE_ERROR' not in repr(server.responses)


@pytest.mark.parametrize('mode', ['headers', 'body'])
def test_cancellation_waits_for_owned_upstream_exit_and_holds_lock_through_repeated_cancel(tmp_path, monkeypatch, mode):
    raw = complete_wire()
    plan = {'mode': 'wait_headers', 'body': raw} if mode == 'headers' else {'body': raw, 'split': raw.index(b'\n\n')+2}
    with gateway(tmp_path, [plan]) as (server, ledger, received, first, release):
        entered, allow_close = Event(), Event()
        transport = server._provider_transport
        original = transport._cancel_stream
        async def delayed(state):
            entered.set()
            while not allow_close.is_set(): await asyncio.sleep(.001)
            await original(state)
        monkeypatch.setattr(transport, '_cancel_stream', delayed)
        async def run():
            handle = server.open_candidate_response(body())
            task = asyncio.create_task(consume(handle))
            assert await asyncio.to_thread(first.wait, 1)
            task.cancel()
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()  # 第二次取消不能打断关闭，或提前释放AE active对应上下文。
            await asyncio.sleep(.01)
            assert not task.done() and server._paid_lock.locked()
            assert len(server._streams) == 1 and handle.request_id in server._candidate_handles
            waiter = asyncio.create_task(handle.wait_closed())
            await asyncio.sleep(.01)
            assert not waiter.done() and ledger.status()['unknown_or_inflight'] == 1
            allow_close.set()
            with pytest.raises(asyncio.CancelledError): await task
            ack = await asyncio.wait_for(waiter, 1)
            assert ack['owned_upstream_exited'] and not ack['provider_compute_stopped'] and not ack['usage_settled']
            assert handle._upstream.state.task.done() and handle._upstream.state.done.is_set()
        try: asyncio.run(run())
        finally: allow_close.set(); release.set()
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 1
        assert not server._paid_lock.locked() and not server._streams and not server._candidate_handles
        assert records(ledger)[0][:3] == ('client_disconnected', 0, 0)


def test_explicit_request_id_cancel_before_headers_is_acknowledged_and_never_cancels_formal_request(tmp_path):
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': complete_wire()}]) as (server, ledger, received, first, release):
        async def run():
            handle = server.open_candidate_response(body())
            task = asyncio.create_task(consume(handle))
            assert await asyncio.to_thread(first.wait, 1)
            with pytest.raises(ValueError, match='candidate_handle_not_active'):
                await server.cancel_candidate('formal-attempt-id-is-not-a-candidate')
            ack = await server.cancel_candidate(handle.request_id)
            assert ack['owned_upstream_exited'] and not ack['usage_settled']
            with pytest.raises((OSError, ValueError)): await task
            assert (await handle.wait_closed()) == ack
        asyncio.run(run())
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 1


def test_cancel_waiting_for_shared_lock_makes_no_request_and_does_not_late_acquire(tmp_path):
    with gateway(tmp_path, []) as (server, ledger, received, _, __):
        async def run():
            server._paid_lock.acquire()
            handle = server.open_candidate_response(body())
            task = asyncio.create_task(consume(handle))
            await asyncio.sleep(.01)
            ack = await handle.cancel()
            server._paid_lock.release()
            with pytest.raises(ValueError, match='candidate_request_cancelled'): await task
            assert ack['owned_upstream_exited'] and ack['ledger_finalized'] and not ack['usage_settled']
            assert not server._paid_lock.locked()
        asyncio.run(run())
        assert not received and ledger.status()['attempt_count'] == 0


def test_global_gateway_close_interrupts_preheader_candidate_and_ack_remains_local(tmp_path):
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': complete_wire()}]) as (server, ledger, received, first, release):
        async def run():
            handle = server.open_candidate_response(body())
            task = asyncio.create_task(consume(handle))
            assert await asyncio.to_thread(first.wait, 1)
            await asyncio.to_thread(server.close)
            with pytest.raises((OSError, ValueError)): await task
            ack = await asyncio.wait_for(handle.wait_closed(), 1)
            assert ack['owned_upstream_exited'] and not ack['usage_settled']
        asyncio.run(run())
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 1


def test_host_deadline_explicitly_cancels_preheader_upstream_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate_module, 'MAX_SECONDS', .03)
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': complete_wire()}]) as (server, ledger, received, first, release):
        async def run():
            handle = server.open_candidate_response(body())
            with pytest.raises((OSError, ValueError)):
                await asyncio.wait_for(consume(handle), 1)
            ack = await handle.wait_closed()
            assert ack['owned_upstream_exited'] and not ack['usage_settled']
        asyncio.run(run())
        assert len(received) == 1 and ledger.status()['unknown_or_inflight'] == 1
        assert not server._paid_lock.locked()


def preemptive_sources():
    root = Path(os.environ.get('LONGMEMORY_TEST_PREEMPTIVE_SOURCES',
        str(Path(__file__).resolve().parents[3]/'scripts/development/xiaozhi')))
    modules = []
    for file in ('voice_preemptive.py', 'voice_preemptive_stream.py'):
        path = root/file
        if not path.is_file():
            pytest.skip('AE sources required in combined tree or explicit isolated source snapshot')
        name = 'af_combined_'+path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


@pytest.mark.parametrize('mode', ['complete', 'headers_cancel', 'body_cancel'])
def test_actual_ae_controller_does_not_release_shared_slot_before_owned_ack(tmp_path, monkeypatch, mode):
    p, s = preemptive_sources()
    raw = complete_wire()
    plan = {'body': raw}
    if mode == 'headers_cancel': plan['mode'] = 'wait_headers'
    if mode == 'body_cancel': plan['split'] = raw.index(b'\n\n')+2
    # baedad5 AE只接受小写；精确学校大写名称由AE/AI接线，AF不静默替换身份。
    with gateway(tmp_path, [plan], model='deepseek-v4-flash') as (server, ledger, received, first, release):
        entered, allow_close = Event(), Event()
        original = server._provider_transport._cancel_stream
        async def delayed(state):
            entered.set()
            while not allow_close.is_set(): await asyncio.sleep(.001)
            await original(state)
        if mode != 'complete': monkeypatch.setattr(server._provider_transport, '_cancel_stream', delayed)
        async def run():
            model = s.GatewayPreparationModel(**server.candidate_response_binding())
            controller = p.VoicePreemptive(model, p.RequestBudget(max_active=1), limits=p.Limits(enabled=True))
            version = p.SnapshotVersion('synthetic-memory', 'synthetic-context', 'no-tools', 'synthetic-policy')
            context = p.ContextSnapshot(version, (('system', '合成角色与已冻结规则'),))
            turn = p.TurnStamp(1, 0, 0)
            assert controller.provisional(turn=turn, transcript='合成当前问题', context=context)
            if mode == 'complete':
                lease = await controller.confirmed(turn=turn, transcript='合成当前问题', context=context)
                assert lease is not None and lease.claim(turn=turn, context=context) == '合成回答'
                assert await controller.aclose()
                assert controller.budget.active == 0 and controller.snapshot()['hits'] == 1
            else:
                assert await asyncio.to_thread(first.wait, 1)
                controller.continued(turn_id=1, cancel_epoch=1)
                assert await asyncio.to_thread(entered.wait, 1)
                assert not await controller.aclose(timeout_seconds=.02)
                assert controller.budget.active == 1 and server._paid_lock.locked()
                assert ledger.status()['unknown_or_inflight'] == 1
                allow_close.set()
                assert await controller.aclose(timeout_seconds=1)
                assert controller.budget.active == 0 and not server._paid_lock.locked()
                assert controller.snapshot()['ready'] == controller.snapshot()['hits'] == 0
            assert '合成当前问题' not in repr(controller.snapshot())
        try: asyncio.run(run())
        finally: allow_close.set(); release.set()
        assert len(received) == 1
        assert ledger.status()['unknown_or_inflight'] == (0 if mode == 'complete' else 1)
