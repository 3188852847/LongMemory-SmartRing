"""v2运行时协商、混合版本与实际callback边界；不加载模型或真实SDK。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import subprocess
from threading import Event,RLock
from types import SimpleNamespace as NS

import pytest

from longmemory.methods.hy_memory import observation as module
from longmemory.methods.hy_memory import sdk_observation as sdk
from longmemory.methods.hy_memory import process_client, worker
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError


TRACE='a'*32


def packet(version, stage):
    return {'version':version,'trace_id':TRACE,'stages':{stage:{'calls':1,'total_ms':3.0}}}


def test_default_details_have_no_clocks_or_packets_and_base_stays_v1(monkeypatch):
    observation=module.Observation(TRACE)
    monkeypatch.setattr(module,'perf_counter',lambda:pytest.fail('disabled detail clock'))
    with observation.activate(), module.span('embed_client_get_ms'):
        observation.add('embed_http_headers_ms',2)
    assert observation.detail_snapshot() is None
    assert module.response_headers(observation)=={'X-Memory-Observation':module.header(observation)}
    assert module.valid_snapshot(observation.snapshot(),TRACE)
    assert not module.valid_snapshot(packet(1,'embed_client_get_ms'),TRACE)


@pytest.mark.parametrize('bad',[None,{},True,'secret', {'version':1},
    {'version':2,'trace_id':'b'*32,'stages':{}},
    {'version':2,'trace_id':TRACE,'stages':{'unknown':{'calls':1,'total_ms':1}}},
    packet(True,'embed_client_get_ms'),packet(2,'sdk_execute_ms')])
def test_invalid_detail_preserves_base_and_is_not_available(bad):
    observation=module.Observation(TRACE,detail=True)
    observation.merge(packet(1,'sdk_execute_ms'))
    before=module.header(observation)
    observation.merge_detail(bad)
    assert module.header(observation)==before and observation.detail_snapshot() is None


def test_separate_packets_and_combined_header_limit(monkeypatch):
    observation=module.Observation(TRACE,detail=True)
    observation.merge(packet(1,'sdk_execute_ms'))
    observation.merge_detail(packet(2,'embed_client_get_ms'))
    headers=module.response_headers(observation)
    assert json.loads(headers['X-Memory-Observation'])==packet(1,'sdk_execute_ms')
    assert json.loads(headers['X-Memory-Observation-Detail'])==packet(2,'embed_client_get_ms')
    monkeypatch.setattr(module,'HEADER_LIMIT',max(map(len,headers.values())))
    assert module.response_headers(observation)=={'X-Memory-Observation':headers['X-Memory-Observation']}


@pytest.mark.parametrize('version',[None,'1','first-recall-v1','3',2])
def test_gateway_requires_explicit_string_version_and_same_trace(version):
    assert module.embedding_observation(TRACE,version) is None
    assert module.embedding_observation('private', '2') is None
    observation=module.embedding_observation(TRACE,'2')
    module.merge_embedding_header(observation,json.dumps(packet(2,'embed_client_get_ms')))
    assert observation.detail_snapshot() is None  # 网关只拥有3个固定阶段。
    module.merge_embedding_header(observation,json.dumps(packet(2,'embed_gateway_ms')))
    assert observation.detail_snapshot()==packet(2,'embed_gateway_ms')


@pytest.mark.parametrize('error',[False,True])
def test_get_client_wrapper_preserves_identity_and_exception(error):
    expected=object(); calls=[]; failure=RuntimeError('private')
    def original():
        calls.append(1)
        if error: raise failure
        return expected
    observed=sdk._wrap(original,'embed_client_get_ms')
    observation=module.Observation(TRACE,detail=True)
    with observation.activate():
        if error:
            with pytest.raises(RuntimeError) as caught: observed()
            assert caught.value is failure
        else:
            assert observed() is expected
    assert calls==[1] and observation.detail_stages['embed_client_get_ms']['calls']==1
    assert 'private' not in repr(observation.detail_snapshot())


@pytest.mark.parametrize('cancel_at',[None,'queued','started'])
def test_vdb_executor_callback_is_once_and_cancel_does_not_late_mutate(cancel_at):
    # 小型专属执行器测试包装语义；真实SDK执行器另由集成测试验。
    calls=[]; gate=Event(); started=Event(); finished=Event(); blocker_entered=Event()
    expected=object()
    with ThreadPoolExecutor(max_workers=1) as executor:
        if cancel_at=='queued':
            def block(): blocker_entered.set(); gate.wait(3)
            blocking=executor.submit(block)
            assert blocker_entered.wait(1)
        async def original(func,*args,**kwargs):
            return await asyncio.shield(asyncio.get_running_loop().run_in_executor(executor,lambda:func(*args,**kwargs)))
        def callback(value):
            calls.append(value); started.set()
            if cancel_at=='started': assert gate.wait(3)
            finished.set()
            return expected
        wrapped=sdk._wrap_vdb_pool(original)
        observation=module.Observation(TRACE,detail=True)
        async def search(): return await wrapped(callback,'private')
        async def scenario():
            with observation.activate():
                task=asyncio.create_task(sdk._wrap(search,'vdb_query_ms')())
                await asyncio.sleep(0)
                if cancel_at is None:
                    assert await task is expected
                    return
                if cancel_at=='started':
                    while not started.is_set(): await asyncio.sleep(.001)
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                before=deepcopy(observation.detail_snapshot())
                gate.set()
                while not finished.is_set(): await asyncio.sleep(.001)
                await asyncio.sleep(0)
                assert observation.detail_snapshot()==before
        try: asyncio.run(scenario())
        finally: gate.set()
    assert calls==['private']
    stages=observation.detail_stages
    assert ('vdb_query_pool_wait_ms' in stages)==(cancel_at!='queued')
    assert ('vdb_query_backend_ms' in stages)==(cancel_at is None)
    assert 'private' not in repr(stages)


def test_worker_detail_support_and_reply_size_are_optional(monkeypatch):
    observation=module.Observation(TRACE,detail=True)
    observation.add('sdk_execute_ms',1)
    observation.merge_detail(packet(2,'embed_client_get_ms'))
    response={'id':1,'ok':True,'result':{'original':True}}
    encoded=worker.encode_response(dict(response),observation)
    base=deepcopy(json.loads(encoded));base.pop('observation_detail')
    monkeypatch.setattr(worker,'MAX_LINE',len(json.dumps(base,ensure_ascii=False)))
    assert json.loads(worker.encode_response(dict(response),observation))==base
    assert not worker.detail_supported(NS(budget=NS()))
    assert worker.detail_supported(NS(budget=NS(sdk_observation=NS(applied=True))))


@pytest.mark.parametrize('fail',[False,True])
def test_gateway_existing_lock_encoder_counters_and_error_are_preserved(fail):
    from longmemory.methods.hy_memory.model_gateway import ModelGateway
    order=[];failure=RuntimeError('private encoding input')
    class Encoder:
        identity='f'*64
        def encode_query(self,text):
            order.append('encode')
            if fail:raise failure
            return [1.0,0.0]
    class Lock:
        def __enter__(self):order.append('lock')
        def __exit__(self,*args):order.append('unlock')
    gateway=object.__new__(ModelGateway);gateway.encoder=Encoder();gateway._embedding_lock=Lock()
    gateway.embedding_calls=gateway.embedding_inputs=0
    observation=module.Observation(TRACE,detail=True)
    with observation.activate():
        if fail:
            with pytest.raises(RuntimeError) as caught:gateway.embed({'model':Encoder.identity,'input':'private'},'query')
            assert caught.value is failure
        else:
            assert gateway.embed({'model':Encoder.identity,'input':'private'},'query')['data'][0]['embedding']==[1.0,0.0]
    assert order==['lock','encode','unlock']
    assert gateway.embedding_calls==gateway.embedding_inputs==(0 if fail else 1)
    assert set(observation.detail_stages)==module.GATEWAY_STAGES
    assert all(item['calls']==1 for item in observation.detail_stages.values())
    assert 'private' not in repr(observation.detail_snapshot())


@pytest.mark.parametrize('capability',[None,[],[1],[True],[2,3],[2]])
@pytest.mark.parametrize('enabled',[False,True])
def test_parent_only_requests_negotiated_detail_and_preserves_base(tmp_path,capability,enabled):
    initialize={'ready':True}
    if capability is not None: initialize['observation_detail_versions']=capability
    script="""import json,sys
first=json.loads(sys.stdin.readline())
print(json.dumps({'id':first['id'],'ok':True,'result':INITIALIZE}),flush=True)
for line in sys.stdin:
    req=json.loads(line)
    if req['operation']=='close':
        print(json.dumps({'id':req['id'],'ok':True,'result':{}}),flush=True);break
    print(json.dumps({'id':req['id'],'ok':True,'result':req,
        'observation':{'version':1,'trace_id':req['observation_id'],'stages':{'sdk_execute_ms':{'calls':1,'total_ms':3.0}}},
        'observation_detail':{'version':2,'trace_id':req['observation_id'],'stages':{'embed_client_get_ms':{'calls':1,'total_ms':3.0}}}}),flush=True)
""".replace('INITIALIZE',repr(initialize))
    client=process_client.HyProcessClient(python=Path(sys.executable),workspace=tmp_path,
        settings=HySettings(user_id='synthetic-v2'),create=True,
        command=[sys.executable,'-I','-c',script])
    observation=module.Observation(TRACE,detail=enabled)
    try:
        with observation.activate(): request=client.diagnostics()
        expected=enabled and capability==[2]
        assert ('observation_detail_version' in request)==expected
        assert (observation.detail_snapshot() is not None)==expected
        assert observation.stages['sdk_execute_ms']=={'calls':1,'total_ms':3.0}
    finally: client.close()


@pytest.mark.parametrize('version',[None,True,1,3,2])
@pytest.mark.parametrize('supported',[False,True])
def test_worker_only_enables_detail_after_explicit_capability(monkeypatch,version,supported):
    class Service:
        client=None
        budget=NS(sdk_observation=NS(applied=supported))
        def execute(self,operation,arguments):
            module.CURRENT.get().add('embed_client_get_ms',1)
            return {'original':True}
    request={'id':1,'operation':'search','arguments':{},'observation_id':TRACE}
    if version is not None: request['observation_detail_version']=version
    source=io.StringIO(json.dumps(request)+'\n');target=io.StringIO()
    monkeypatch.setattr(worker.sys,'stdin',source);monkeypatch.setattr(worker.sys,'stdout',target)
    worker.main(service=Service())
    response=json.loads(target.getvalue())
    assert response['result']=={'original':True} and response['observation']['version']==1
    assert ('observation_detail' in response)==(supported and type(version) is int and version==2)


def test_request_limit_drops_only_optional_detail_flag(monkeypatch):
    client=object.__new__(process_client.HyProcessClient)
    client._lock=RLock();client._closed=False;client._counter=0;client.timeout=1
    client._observation_detail_supported=True
    payloads=[]
    client._process=NS(stdin=NS(write=payloads.append,flush=lambda:None))
    client._responses=NS(get=lambda **kwargs:json.dumps({'id':1,'ok':True,'result':{'original':True}}))
    base={'id':1,'operation':'diagnostics','arguments':{},'observation_id':TRACE}
    monkeypatch.setattr(process_client,'MAX_LINE',len(json.dumps(base,ensure_ascii=False)))
    observation=module.Observation(TRACE,detail=True)
    with observation.activate():assert client.diagnostics()=={'original':True}
    assert json.loads(payloads[0])==base
    assert observation.detail_snapshot() is None


def test_immutable_c74_parent_accepts_new_worker_and_keeps_v1(tmp_path):
    root=Path(__file__).resolve().parents[3]
    source=subprocess.run(['git','show','c74b88834683080d4dc4ee4b770f48707ff5b349:src/longmemory/methods/hy_memory/process_client.py'],
        cwd=root,capture_output=True)
    if source.returncode:pytest.skip('immutable baseline unavailable; no fetch')
    namespace={'__name__':'longmemory.methods.hy_memory._c74_parent',
        '__package__':'longmemory.methods.hy_memory',
        '__file__':str(root/'src/longmemory/methods/hy_memory/process_client.py')}
    exec(compile(source.stdout,'<immutable-c74-parent>','exec'),namespace)
    script='import sys;sys.path.insert(0,'+repr(str(root/'src'))+')\n'+'''
from types import SimpleNamespace as NS
from longmemory.methods.hy_memory.worker import main
from longmemory.methods.hy_memory.observation import CURRENT
class Service:
    client=None
    budget=NS(sdk_observation=NS(applied=True))
    def execute(self,operation,arguments):
        if operation=='initialize':return {'ready':True,'observation_detail_versions':[2]}
        if operation=='close':return {'closed':True}
        observation=CURRENT.get()
        assert observation is not None and not observation.detail_enabled
        observation.add('embed_client_get_ms',1)
        return {'original':True}
main(service=Service())
'''
    client=namespace['HyProcessClient'](python=Path(sys.executable),workspace=tmp_path,
        settings=HySettings(user_id='synthetic-old-parent'),create=True,
        command=[sys.executable,'-I','-c',script])
    observation=module.Observation(TRACE)
    try:
        with observation.activate():assert client.diagnostics()=={'original':True}
        assert 'sdk_execute_ms' in observation.stages
        assert 'embed_client_get_ms' not in observation.stages
    finally:client.close()
