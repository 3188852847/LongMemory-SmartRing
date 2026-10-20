"""固定数值观测契约、异常清理和异步同轮隔离；不启动服务。"""

import asyncio
from copy import deepcopy
import json

import pytest

from longmemory.methods.hy_memory import observation as module
from longmemory.methods.hy_memory.observation import CURRENT, STAGES, Observation, header, measured, span, valid_snapshot


TRACE = 'a' * 32


@pytest.mark.parametrize('trace', ['', 'a' * 23, 'a' * 33, 'A' * 32, 'g' * 24, None, 1, ' a' * 16])
def test_trace_identity_rejects_non_anonymous_or_invalid_shapes(trace):
    with pytest.raises(ValueError, match='identity_invalid'):
        Observation(trace)


def test_snapshot_fixed_numeric_schema_order_copy_and_bounded_header():
    observation = Observation(TRACE)
    for stage in reversed(sorted(STAGES)):
        observation.add(stage, 1.23456)
    snapshot = observation.snapshot()
    assert list(snapshot) == ['version', 'trace_id', 'stages']
    assert list(snapshot['stages']) == sorted(STAGES)
    assert all(item == {'calls': 1, 'total_ms': 1.235} for item in snapshot['stages'].values())
    assert valid_snapshot(snapshot, TRACE)
    encoded = header(observation)
    assert len(encoded) <= 4096 and json.loads(encoded) == snapshot
    snapshot['stages']['api_queue_ms']['calls'] = 99
    assert observation.snapshot()['stages']['api_queue_ms']['calls'] == 1


@pytest.mark.parametrize('stage,value,calls', [('question_body', 1, 1), ('api_queue_ms', True, 1),
    ('api_queue_ms', float('inf'), 1), ('api_queue_ms', float('nan'), 1),
    ('api_queue_ms', -1, 1), ('api_queue_ms', 10**400, 1), ('api_queue_ms', 'private-text', 1),
    ('api_queue_ms', 1, True), ('api_queue_ms', 1, 0), ('api_queue_ms', 1, 100001)])
def test_add_discards_unknown_or_non_finite_non_numeric_payloads(stage, value, calls):
    observation = Observation(TRACE)
    observation.add(stage, value, calls=calls)
    assert observation.snapshot()['stages'] == {}


def test_merge_accumulates_accepted_same_trace_only_and_does_not_alias():
    observation = Observation(TRACE)
    observation.add('sdk_roundtrip_ms', 3)
    source = Observation(TRACE)
    source.add('sdk_roundtrip_ms', 4.25, calls=2)
    source.add('sdk_execute_ms', 1)
    snapshot = source.snapshot()
    observation.merge(snapshot)
    snapshot['stages']['sdk_roundtrip_ms']['total_ms'] = 999
    assert observation.snapshot()['stages'] == {
        'sdk_execute_ms': {'calls': 1, 'total_ms': 1.0},
        'sdk_roundtrip_ms': {'calls': 3, 'total_ms': 7.25}}
    foreign = Observation('b' * 24)
    foreign.add('sdk_roundtrip_ms', 100)
    before = observation.snapshot()
    observation.merge(foreign.snapshot())
    assert observation.snapshot() == before


@pytest.mark.parametrize('mutation', ['extra_root', 'unknown_stage', 'extra_item', 'version_bool',
    'version_future', 'trace_foreign', 'calls_bool', 'calls_zero', 'calls_large',
    'time_bool', 'time_negative', 'time_nan', 'time_infinite', 'time_large', 'time_huge_integer', 'not_mapping'])
def test_invalid_remote_snapshot_is_rejected_atomically(mutation):
    source = Observation(TRACE)
    source.add('sdk_execute_ms', 5)
    snapshot = source.snapshot()
    item = snapshot['stages']['sdk_execute_ms']
    if mutation == 'extra_root': snapshot['body'] = 'synthetic-private'
    elif mutation == 'unknown_stage': snapshot['stages']['question'] = dict(item)
    elif mutation == 'extra_item': item['question'] = 'synthetic-private'
    elif mutation == 'version_bool': snapshot['version'] = True
    elif mutation == 'version_future': snapshot['version'] = 2
    elif mutation == 'trace_foreign': snapshot['trace_id'] = 'b' * 32
    elif mutation == 'calls_bool': item['calls'] = True
    elif mutation == 'calls_zero': item['calls'] = 0
    elif mutation == 'calls_large': item['calls'] = 100001
    elif mutation == 'time_bool': item['total_ms'] = True
    elif mutation == 'time_negative': item['total_ms'] = -1
    elif mutation == 'time_nan': item['total_ms'] = float('nan')
    elif mutation == 'time_infinite': item['total_ms'] = float('inf')
    elif mutation == 'time_large': item['total_ms'] = 3600001
    elif mutation == 'time_huge_integer': item['total_ms'] = 10**400
    elif mutation == 'not_mapping': snapshot = []
    assert not valid_snapshot(snapshot, TRACE)
    observation = Observation(TRACE)
    before = deepcopy(observation.snapshot())
    observation.merge(snapshot)
    assert observation.snapshot() == before


def test_runtime_event_accepts_only_same_trace_and_fixed_timing_names():
    observation = Observation(TRACE)
    observation.runtime_event({'round_id': 'b' * 32, 'timings_ms': {'total_ms': 999}})
    assert observation.snapshot()['stages'] == {}
    observation.runtime_event({'round_id': TRACE, 'timings_ms': {
        'outer_lock_wait_ms': 12, 'total_ms': 15, 'query': 'synthetic-private', 'extra_ms': 300},
        'answer': 'synthetic-private'})
    assert observation.snapshot()['stages'] == {
        'runtime_entry_ms': {'calls': 1, 'total_ms': 15.0},
        'runtime_outer_lock_ms': {'calls': 1, 'total_ms': 12.0}}
    assert 'private' not in header(observation)


def test_span_records_exception_and_restores_nested_context(monkeypatch):
    clock = iter((1.0, 1.005, 2.0, 2.003))
    monkeypatch.setattr(module, 'perf_counter', lambda: next(clock))
    outer, inner = Observation(TRACE), Observation('b' * 32)
    assert CURRENT.get() is None
    with outer.activate():
        with pytest.raises(RuntimeError, match='synthetic-error'):
            with inner.activate(), span('sdk_execute_ms'):
                raise RuntimeError('synthetic-error')
        assert CURRENT.get() is outer
        with span('api_queue_ms'):
            pass
    assert CURRENT.get() is None
    assert inner.snapshot()['stages']['sdk_execute_ms'] == {'calls': 1, 'total_ms': 5.0}
    assert outer.snapshot()['stages']['api_queue_ms'] == {'calls': 1, 'total_ms': 3.0}


def test_inactive_span_does_not_read_clock_and_measured_preserves_result(monkeypatch):
    monkeypatch.setattr(module, 'perf_counter', lambda: pytest.fail('inactive observation must be inert'))
    @measured('archive_ms')
    def original(value):
        """original documentation"""
        return value
    result = object()
    assert original(result) is result
    assert original.__name__ == 'original' and original.__doc__ == 'original documentation'
    with span('sdk_execute_ms'):
        pass


def test_concurrent_async_contexts_and_cancellation_do_not_mix_rounds():
    async def scenario():
        first, second = Observation(TRACE), Observation('b' * 32)
        started, release = asyncio.Event(), asyncio.Event()
        async def cancelled():
            with first.activate(), span('sdk_execute_ms'):
                started.set()
                await release.wait()
        async def completed():
            await started.wait()
            with second.activate(), span('api_queue_ms'):
                await asyncio.sleep(0)
                assert CURRENT.get() is second
        task = asyncio.create_task(cancelled())
        await completed()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert CURRENT.get() is None
        assert set(first.stages) == {'sdk_execute_ms'}
        assert set(second.stages) == {'api_queue_ms'}
        assert first.stages['sdk_execute_ms']['calls'] == second.stages['api_queue_ms']['calls'] == 1
    asyncio.run(scenario())
