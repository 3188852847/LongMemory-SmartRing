"""真实本地HTTP竞争：固定单owned槽、优先FIFO、关闭ACK及原免费审计。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
from threading import Event, Lock
from time import perf_counter

import pytest

from longmemory.methods.hy_memory.model_admission import (
    AdmissionClosed, AdmissionFull, ModelAdmission, work_kind,
)
from test_hy_candidate_response import body, complete_wire, consume, gateway, USAGE


PLAIN = json.dumps({'choices': [{'message': {'content': '合成完整回答'}}], 'usage': USAGE}).encode()


def request(label, *, stream=False):
    return {'model': 'DeepSeek-V4-Flash', 'messages': [{'role': 'system', 'content': '合成固定角色'},
        {'role': 'user', 'content': label}], 'stream': stream, 'max_tokens': 256}


def http_request(server, path, payload=None, *, token=True, method='POST'):
    connection = http.client.HTTPConnection('127.0.0.1', server.server.server_port, timeout=5)
    try:
        headers = {'Content-Type': 'application/json'}
        if token: headers['Authorization'] = 'Bearer '+server.token
        connection.request(method, path, None if payload is None else json.dumps(payload), headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally: connection.close()


async def until(predicate, *, timeout=1):
    loop = asyncio.get_running_loop(); deadline = loop.time()+timeout
    while not predicate():
        if loop.time() >= deadline: raise AssertionError('expected bounded admission condition')
        await asyncio.sleep(.002)


async def hold_barrier(seconds):
    # sleep参数不是实测时长；用与model_queue同源的单调高精度时钟保持屏障。
    deadline = perf_counter()+seconds
    while perf_counter() < deadline:
        await asyncio.sleep(.002)


def test_priority_fifo_and_bounded_queue_do_not_interrupt_inflight_background():
    slot = Lock(); admission = ModelAdmission(slot)
    active = admission.enqueue('background'); assert active.try_acquire() is active
    background = admission.enqueue('background')
    with pytest.raises(AdmissionFull): admission.enqueue('background')
    candidate = admission.enqueue('candidate')
    required = admission.enqueue('required_hy')
    answers = [admission.enqueue('answer'), admission.enqueue('answer')]
    assert not active.preempt_requested
    assert all(ticket.try_acquire() is None for ticket in (*answers, required, candidate, background))
    admission.release(active)
    for ticket in (*answers, required, candidate, background):
        assert ticket.try_acquire() is ticket
        assert slot.locked()
        assert ticket.model_queue_ms is not None
        admission.release(ticket)
        with pytest.raises(AdmissionClosed): ticket.try_acquire()
    assert not slot.locked() and all(value == 0 for value in admission.snapshot()['waiting'].values())


def test_close_wakes_sync_waiter_without_budget_or_late_acquire():
    admission = ModelAdmission(Lock())
    active = admission.enqueue('required_hy'); active.try_acquire()
    def waiting():
        with admission.acquire('answer'): pytest.fail('closed queue must not enter provider')
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(waiting)
        async def wait(): await until(lambda: admission.snapshot()['waiting']['answer'] == 1)
        asyncio.run(wait())
        admission.close()
        with pytest.raises(AdmissionClosed): future.result(timeout=1)
    admission.release(active)
    assert not admission.snapshot()['waiting']['answer']


@pytest.mark.parametrize('value', [None, 'required', 'unknown_sdk_operation'])
def test_unknown_hy_marker_stays_required_foreground(value):
    assert work_kind('hy', value) == 'required_hy'
    assert work_kind('answer', value) == 'answer'
    with pytest.raises(ValueError): work_kind('answer', 'background')


def test_true_http_background_queue_yields_to_answer_then_candidate_with_wait_metrics(tmp_path):
    plans = [{'mode': 'wait_headers', 'body': PLAIN}, {'body': complete_wire()}, {'body': PLAIN},
             {'body': complete_wire()}, {'body': PLAIN}]
    with gateway(tmp_path, plans) as (server, ledger, received, first, release):
        server.__enter__()
        metrics = []
        async def run():
            assert server.local_settings('hy', work_class='background').base_url.endswith('/hy-background/v1')
            assert server.local_settings('hy').base_url.endswith('/hy/v1')
            assert server.background_readiness()['eligible']
            denied = await asyncio.to_thread(http_request, server, '/hy-background/v1/admission', token=False, method='GET')
            assert denied[0] == 401 and ledger.status()['attempt_count'] == 0
            a = asyncio.create_task(asyncio.to_thread(http_request, server, '/hy-background/v1/chat/completions', request('background-a')))
            assert await asyncio.to_thread(first.wait, 1)
            assert not server.background_readiness()['eligible']
            b = asyncio.create_task(asyncio.to_thread(http_request, server, '/hy-background/v1/chat/completions', request('background-b')))
            await until(lambda: server._admission.snapshot()['waiting']['background'] == 1)
            candidate_body = body(); candidate_body['messages'][-1]['content'] = 'candidate'
            candidate = server.open_candidate_response(candidate_body)
            c = asyncio.create_task(consume(candidate))
            await until(lambda: server._admission.snapshot()['waiting']['candidate'] == 1)
            required = asyncio.create_task(asyncio.to_thread(http_request, server, '/hy/v1/chat/completions', request('required-hy')))
            await until(lambda: server._admission.snapshot()['waiting']['required_hy'] == 1)
            answer = asyncio.create_task(asyncio.to_thread(http_request, server, '/voice/v1/chat/completions', request('answer', stream=True)))
            await until(lambda: server._admission.snapshot()['waiting']['answer'] == 1)
            await hold_barrier(.03)  # 明确的合成在飞等待区间；不当学校性能。
            assert len(received) == ledger.status()['attempt_count'] == 1
            assert not candidate._admission_ticket.granted and not answer.done()
            advisory = await asyncio.to_thread(http_request, server, '/hy-background/v1/admission', method='GET')
            assert advisory[0] == 200 and not json.loads(advisory[1])['eligible']
            release.set()
            assert (await a)[0] == (await answer)[0] == (await required)[0] == (await b)[0] == 200
            assert b'[DONE]' in await c
            assert (await candidate.wait_closed())['owned_upstream_exited']
            assert [json.loads(row['body'])['messages'][-1]['content'] for row in received] == ['background-a', 'answer', 'required-hy', 'candidate', 'background-b']
            assert [row['admission_class'] for row in server.responses] == ['background', 'answer', 'required_hy', 'candidate', 'background']
            metrics.extend({key: row[key] for key in ('admission_class', 'model_queue_ms', 'model_queue_by_active_ms', 'model_ttft_ms', 'provider_elapsed_ms')} for row in server.responses)
            assert metrics[1]['model_queue_by_active_ms']['background'] >= 20
            assert metrics[1]['model_ttft_ms'] is not None
            for row in metrics:
                assert abs(sum(row['model_queue_by_active_ms'].values())-row['model_queue_ms']) < .1
            assert server.background_readiness()['eligible'] and not server._paid_lock.locked()
        asyncio.run(run())
        assert ledger.status()['attempt_count'] == 5 and ledger.status()['unknown_or_inflight'] == 0
        (tmp_path/'competition-metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.mark.parametrize('wrong_ack', [False, True])
@pytest.mark.parametrize('foreground_kind', ['answer', 'required_hy'])
def test_answer_preempts_only_candidate_and_waits_actual_matching_ack_before_next_http(tmp_path, monkeypatch, wrong_ack, foreground_kind):
    final_body = complete_wire() if foreground_kind == 'answer' else PLAIN
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': complete_wire()}, {'body': final_body}]) as (server, ledger, received, first, release):
        server.__enter__()
        entered, permit = Event(), Event()
        original = server._provider_transport._cancel_stream
        async def delayed(state):
            entered.set()
            while not permit.is_set(): await asyncio.sleep(.001)
            await original(state)
        monkeypatch.setattr(server._provider_transport, '_cancel_stream', delayed)
        metrics = []
        async def run():
            candidate = server.open_candidate_response(body())
            if wrong_ack:
                original_wait = candidate.wait_closed
                async def wait_closed(): return dict(await original_wait(), request_id='0'*32)
                candidate.wait_closed = wait_closed
            task = asyncio.create_task(consume(candidate))
            assert await asyncio.to_thread(first.wait, 1)
            path = '/voice/v1/chat/completions' if foreground_kind == 'answer' else '/hy/v1/chat/completions'
            answer = asyncio.create_task(asyncio.to_thread(http_request, server, path, request('foreground', stream=foreground_kind=='answer')))
            assert await asyncio.to_thread(entered.wait, 1)
            await hold_barrier(.03)
            assert len(received) == ledger.status()['attempt_count'] == 1
            assert server._paid_lock.locked() and not answer.done()
            permit.set()
            with pytest.raises((OSError, ValueError)): await task
            if wrong_ack:
                await until(lambda: server._admission.snapshot()['quarantined'])
                assert candidate._lease.preempt_requested and not candidate._lease.released
                assert len(received) == 1 and not answer.done()
                await asyncio.to_thread(server.close)
                await asyncio.gather(answer, return_exceptions=True)
            else:
                status, data = await answer
                assert status == 200
                if foreground_kind == 'answer': assert b'[DONE]' in data
                assert not release.is_set()  # owned退出不等于远端处理已经停止。
                assert len(received) == 2 and not server._paid_lock.locked()
                assert candidate._lease.released
                answer_row = next(row for row in server.responses if not row.get('candidate'))
                assert answer_row['admission_class'] == foreground_kind
                assert answer_row['model_queue_by_active_ms']['candidate'] >= 20
                assert (answer_row['model_ttft_ms'] is not None) == (foreground_kind == 'answer')
                metrics.append({key: answer_row[key] for key in ('admission_class', 'model_queue_ms', 'model_queue_by_active_ms', 'model_ttft_ms')})
        try: asyncio.run(run())
        finally: permit.set(); release.set()
        assert ledger.status()['unknown_or_inflight'] == 1
        assert ledger.status()['attempt_count'] == (1 if wrong_ack else 2)
        if not wrong_ack: (tmp_path/'preempt-metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')


def test_formal_request_never_cancelled_queue_cap_no_reservation_and_shutdown_wakes_all(tmp_path):
    with gateway(tmp_path, [{'mode': 'wait_headers', 'body': PLAIN}]) as (server, ledger, received, first, release):
        server.__enter__()
        async def run():
            formal = asyncio.create_task(asyncio.to_thread(http_request, server, '/answer/v1/chat/completions', request('formal')))
            assert await asyncio.to_thread(first.wait, 1)
            background = asyncio.create_task(asyncio.to_thread(http_request, server, '/hy-background/v1/chat/completions', request('background')))
            await until(lambda: server._admission.snapshot()['waiting']['background'] == 1)
            full = await asyncio.to_thread(http_request, server, '/hy-background/v1/chat/completions', request('overflow'))
            assert full[0] == 503
            candidate = server.open_candidate_response(body())
            candidate_task = asyncio.create_task(consume(candidate))
            await until(lambda: server._admission.snapshot()['waiting']['candidate'] == 1)
            other_answer = asyncio.create_task(asyncio.to_thread(http_request, server, '/answer/v1/chat/completions', request('formal-2')))
            await until(lambda: server._admission.snapshot()['waiting']['answer'] == 1)
            assert server._admission.snapshot()['active_class'] == 'answer'
            assert not server._admission._active.preempt_requested
            assert len(received) == ledger.status()['attempt_count'] == 1
            await asyncio.to_thread(server.close)
            results = await asyncio.gather(formal, background, candidate_task, other_answer, return_exceptions=True)
            assert any(isinstance(value, Exception) for value in results)
            assert all(value == 0 for value in server._admission.snapshot()['waiting'].values())
        asyncio.run(run())
        assert ledger.status()['attempt_count'] == 1 and ledger.status()['unknown_or_inflight'] == 1


def test_failed_provider_releases_slot_and_body_priority_does_not_downgrade_formal(tmp_path):
    with gateway(tmp_path, [{'status': 400, 'body': b'{}'}, {'body': PLAIN}, {'body': PLAIN}]) as (server, ledger, received, _, __):
        failed = request('failed')
        assert server.complete('answer', failed)[0] == 502
        assert not server._paid_lock.locked()
        unknown = request('required'); unknown['metadata'] = {'priority': 'background'}
        assert server.complete('hy', unknown, work_class='unclassified')[0] == 200
        formal = request('formal'); formal['metadata'] = {'work_class': 'background'}
        assert server.complete('answer', formal)[0] == 200
        assert [row['admission_class'] for row in server.responses] == ['answer', 'required_hy', 'answer']
        assert ledger.status()['attempt_count'] == 3 and ledger.status()['unknown_or_inflight'] == 1
        assert len(received) == 3
