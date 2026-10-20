"""线程交接与外层锁只用注入时钟；不连接服务或读取声线/个人库。"""

import asyncio
from contextvars import ContextVar, copy_context
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

from longmemory.application import memory_runtime as runtime_module


@pytest.fixture
def provider_module(monkeypatch):
    lines = []
    class Logger:
        def bind(self, **kwargs): return self
        def info(self, template, value): lines.append(json.loads(value))
    monkeypatch.setitem(sys.modules, 'core.providers.memory.base',
                        NS(MemoryProviderBase=object, logger=Logger()))
    monkeypatch.setitem(sys.modules, 'voice_diagnostics', None)
    path = Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi/longmemory_provider.py'
    spec = importlib.util.spec_from_file_location('isolated_provider_timing', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, lines


def provider(module):
    result = object.__new__(module.MemoryProvider)
    result._turn_key = ContextVar('synthetic_turn', default=None)
    return result


def test_handoff_and_physical_request_are_one_call_with_private_fixed_metadata(provider_module, monkeypatch):
    module, lines = provider_module
    p = provider(module); now = [0.0]; calls = []
    monkeypatch.setattr(module, 'perf_counter', lambda: now[0])
    async def to_thread(call):
        now[0] += .2
        return call()
    monkeypatch.setattr(module.asyncio, 'to_thread', to_thread)
    def request(query):
        calls.append(query)
        assert module._REQUEST_TIMING.get()['round_id'] == 'a' * 32
        now[0] += .3
        return 'original result'
    p._request = request
    token = p._turn_key.set('a' * 32)
    try: assert asyncio.run(p.query_memory('private question')) == 'original result'
    finally: p._turn_key.reset(token)
    assert calls == ['private question'] and module._REQUEST_TIMING.get() is None
    assert lines == [{'version': 1, 'round_id': 'a' * 32, 'stage': 'worker_returned', 'status': 'completed',
        'timings_ms': {'thread_handoff_ms': 200.0, 'request_total_ms': 300.0,
                       'handoff_total_ms': 500.0, 'runtime_request_ms': None}}]
    assert 'private' not in repr(lines) and 'original result' not in repr(lines)


def test_cancelled_wait_and_late_worker_remain_separate_original_round(provider_module, monkeypatch):
    module, lines = provider_module
    p = provider(module); now = [0.0]; pending = []; calls = []
    monkeypatch.setattr(module, 'perf_counter', lambda: now[0])
    async def to_thread(call):
        context = copy_context()
        pending.append(lambda: context.run(call))
        return await asyncio.Future()
    monkeypatch.setattr(module.asyncio, 'to_thread', to_thread)
    def request(query):
        calls.append(p._turn_key.get())
        now[0] += .3
        return 'old physical return'
    p._request = request
    async def scenario():
        old = p._turn_key.set('a' * 32)
        task = asyncio.create_task(p.query_memory('old private question'))
        await asyncio.sleep(0)
        now[0] = .1; task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        p._turn_key.reset(old)
        new = p._turn_key.set('b' * 32)
        try:
            now[0] = .5
            assert pending.pop()() == 'old physical return'
        finally: p._turn_key.reset(new)
    asyncio.run(scenario())
    assert calls == ['a' * 32]
    assert [item['round_id'] for item in lines] == ['a' * 32, 'a' * 32]
    assert [item['stage'] for item in lines] == ['consumer_cancelled', 'worker_returned']
    assert lines[0]['timings_ms']['thread_handoff_ms'] is None
    assert lines[1]['timings_ms']['thread_handoff_ms'] == 500
    assert lines[1]['timings_ms']['request_total_ms'] == 300
    assert module._REQUEST_TIMING.get() is None


def test_error_and_logger_failure_never_change_original_result(provider_module, monkeypatch):
    module, lines = provider_module
    p = provider(module)
    async def to_thread(call): return call()
    monkeypatch.setattr(module.asyncio, 'to_thread', to_thread)
    error = RuntimeError('private error body')
    def fail(query): raise error
    p._request = fail
    with pytest.raises(RuntimeError) as caught: asyncio.run(p.query_memory('private question'))
    assert caught.value is error and lines[-1]['status'] == 'failed'
    assert 'private' not in repr(lines)
    monkeypatch.setattr(module.logger, 'info', lambda *a: (_ for _ in ()).throw(OSError('log failed')))
    p._request = lambda query: 'unchanged'
    assert asyncio.run(p.query_memory('private')) == 'unchanged'


def test_runtime_request_times_original_single_http_call_without_changing_body(provider_module, monkeypatch):
    module, lines = provider_module
    p=provider(module);p._session_id='b'*32;now=[0.0];requests=[]
    monkeypatch.setattr(module,'perf_counter',lambda:now[0])
    monkeypatch.setenv('LONGMEMORY_RUNTIME_URL','http://127.0.0.1:19999/api/internal/memory/prepare')
    monkeypatch.setenv('LONGMEMORY_RUNTIME_TOKEN','c'*64)
    class Lock:
        def __enter__(self):now[0]+=.1
        def __exit__(self,*args):pass
    class Response:
        status=200
        headers={'X-Memory-Observation':json.dumps({'version':1,'trace_id':'a'*32,
            'stages':{'sdk_execute_ms':{'calls':1,'total_ms':10**400}}})}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):
            assert limit==65537
            now[0]+=.05
            return b'{"original":"private context"}'
    def urlopen(request,timeout):
        requests.append((json.loads(request.data),timeout));now[0]+=.2
        return Response()
    monkeypatch.setattr(module.urlrequest,'urlopen',urlopen)
    async def to_thread(call):now[0]+=.025;return call()
    monkeypatch.setattr(module.asyncio,'to_thread',to_thread)
    p._lock=Lock();p._request=p._runtime_request
    token=p._turn_key.set('a'*32)
    try:
        assert asyncio.run(p.query_memory('private question'))=={'original':'private context'}
    finally:p._turn_key.reset(token)
    assert requests==[({'version':1,'query':'private question','client_round_id':'a'*32,'session_id':'b'*32},20)]
    assert lines[0]['timings_ms']=={'thread_handoff_ms':25.0,'request_total_ms':350.0,
        'handoff_total_ms':375.0,'runtime_request_ms':350.0}
    assert 'private' not in repr(lines) and 'c'*64 not in repr(lines)


@pytest.mark.parametrize('fail',[False,True])
def test_roundscreen_outer_lock_is_counted_without_changing_prepare_or_order(monkeypatch, fail):
    now = [0.0]; order = []; records = []; held = [False]
    monkeypatch.setattr(runtime_module, 'perf_counter', lambda: now[0])
    class Lock:
        def __enter__(self): now[0] += .8; held[0] = True
        def __exit__(self, *args): held[0] = False
    def log(template, payload):
        assert not held[0]
        records.append(json.loads(payload))
    monkeypatch.setattr(runtime_module._LOGGER, 'info', log)
    rt = object.__new__(runtime_module.MemoryRuntime)
    rt._lock = Lock(); rt._deferred_events = {}; rt._proposal_formal = {}
    rt._ensure_open = lambda: order.append('open')
    prepared = NS(event=NS(event_id='original-event'), timings=object(),
                  support=NS(context='synthetic'), memory_command=None, follow_up_suggestion=None)
    original_feedback = {'recorded': False}
    original_timings = prepared.timings
    error = RuntimeError('private sdk exception')
    def step(name, seconds, result=None):
        assert held[0]
        order.append(name); now[0] += seconds
        return result
    def prepare(text, **kwargs):
        assert kwargs['defer_slow_observation'] is True
        step('prepare', .021)
        if fail: raise error
        return prepared
    rt.prepare_user = prepare
    rt._round_screen_store = NS(expire=lambda: step('expire', .01, ()),
        reserve=lambda **kwargs: step('reserve', .02, 'original-event'),
        prepared=lambda *args: step('prepared', .03), failed=lambda *args: step('failed', .03),
        feedback=lambda *args: step('feedback', .04, original_feedback))
    monkeypatch.setattr(runtime_module, 'memory_receipt', lambda value: {'evidence': []})
    if fail:
        with pytest.raises(RuntimeError) as caught:
            rt.prepare_round_screen('private text', client_round_id='a'*32, session_id='b'*32)
        assert caught.value is error
        assert order == ['open','expire','reserve','prepare','failed']
    else:
        result = rt.prepare_round_screen('private text', client_round_id='a'*32, session_id='b'*32)
        assert result == (prepared,original_feedback) and prepared.timings is original_timings
        assert order == ['open','expire','reserve','prepare','prepared','feedback']
    assert records == [{'version':1,'round_id':'a'*32,'status':'failed' if fail else 'completed',
                        'timings_ms':{'outer_lock_wait_ms':800.0,'total_ms':881.0 if fail else 921.0}}]
    assert 'private' not in repr(records)


def test_invalid_round_metadata_is_never_copied_into_observation(monkeypatch):
    records=[]
    monkeypatch.setattr(runtime_module._LOGGER,'info',lambda template,payload:records.append(json.loads(payload)))
    from threading import RLock
    rt=object.__new__(runtime_module.MemoryRuntime);rt._lock=RLock();rt._ensure_open=lambda:None
    with pytest.raises(ValueError,match='metadata_invalid'):
        rt.prepare_round_screen('private text',client_round_id='private bad id',session_id='a'*32)
    assert records[0]['round_id'] is None and 'private' not in repr(records)
    monkeypatch.setattr(runtime_module._LOGGER,'info',lambda *args:(_ for _ in ()).throw(OSError('log failed')))
    with pytest.raises(ValueError,match='metadata_invalid'):
        rt.prepare_round_screen('private text',client_round_id='private bad id',session_id='a'*32)


def test_provider_observation_header_exact_schema_matches_server_and_discards_foreign_or_private_fields(provider_module):
    from longmemory.methods.hy_memory.observation import Observation, STAGES, header
    module, _ = provider_module
    assert module._OBSERVATION_STAGES == STAGES
    observation = Observation('a' * 32)
    observation.add('sdk_search_ms', 12.5)
    expected = observation.snapshot()
    assert module._observation_header(header(observation), 'a' * 32) == expected
    assert module._observation_header(header(observation), 'b' * 32) is None
    assert module._observation_header(None, 'a' * 32) is None
    assert module._observation_header('x' * 4097, 'a' * 32) is None
    assert module._observation_header('invalid-json', 'a' * 32) is None
    for unsafe in (
        {**expected, 'body': 'private transcript'},
        {**expected, 'version': True},
        {**expected, 'stages': {'private query': {'calls': 1, 'total_ms': 1}}},
        {**expected, 'stages': {'sdk_search_ms': {'calls': True, 'total_ms': 1}}},
        {**expected, 'stages': {'sdk_search_ms': {'calls': 1, 'total_ms': float('nan')}}},
        {**expected, 'stages': {'sdk_search_ms': {'calls': 1, 'total_ms': 10**400}}},
        {**expected, 'stages': {'sdk_search_ms': {'calls': 1, 'total_ms': 1, 'key': 'private'}}},
    ):
        assert module._observation_header(json.dumps(unsafe), 'a' * 32) is None
