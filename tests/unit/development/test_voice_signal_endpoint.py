"""自有随机回环HTTP验证诊断端点和原状态的各自整包预算；无设备/模型。"""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace as NS

import aiohttp
from aiohttp.test_utils import TestClient, TestServer
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts/development/xiaozhi'))
    return tuple(importlib.import_module(name) for name in ('voice_signal_diagnostics', 'device_control', 'control_http'))


def maximum_signal(module):
    def group(recent=False):
        energy = {name:dict(max_rms_pcm16=32767.999) for name in module.STAGES}
        if not recent:
            for item in energy.values():item.update(last_rms_pcm16=32767.999, max_peak_pcm16=32768)
        probability = dict(min=.12345678901234568, max=.9999999999999999)
        probability.update(count=module.LIMIT) if recent else probability.update(bins=[module.LIMIT]*7)
        return dict(counts=[module.LIMIT]*len(module.COUNT_KEYS), energy=energy, probability=probability)
    value = module.missing('observed')
    value.update(groups={phase:group() for phase in module.PHASES},
                 recent_groups={phase:group(True) for phase in module.PHASES},
                 contract=dict(session_observed=True, threshold=.9999999999999999,
                    threshold_low=.12345678901234568, silence_threshold_ms=60000.,
                    frame_window_threshold=100., runtime_model_hash=None),
                 aec_reference=dict(timestamp_nonzero=True, reference_present=True,
                    nearest_reference_abs_delta_ms=2**31, reference_count=module.LIMIT),
                 window_positive_count=100)
    return value


def test_getter_only_uses_current_live_connection_and_never_caches(modules, monkeypatch):
    signal, device, _ = modules
    calls=[]
    def get(conn):
        calls.append(conn)
        return signal.missing('no_connection') if conn is None else maximum_signal(signal)
    monkeypatch.setitem(sys.modules, 'voice_vad_signal_observation', NS(voice_vad_signal_snapshot=get))
    control=device.DeviceControl('synthetic')
    live=NS(websocket=NS(state=NS(name='OPEN')))
    control.attach(live,'synthetic')
    assert control.voice_input_signal()['state']=='observed'
    # 不要求MCP或绑定工具；只读取已经认证附着且当前OPEN的连接。
    control.detach(live)
    assert control.voice_input_signal()['state']=='no_connection'
    assert calls == [live,None]
    control.attach(live,'synthetic');live.websocket.state.name='CLOSED'
    assert control.voice_input_signal()['state']=='no_connection'
    control.attach(NS(),'synthetic')
    assert control.voice_input_signal()['state']=='unavailable'
    assert calls == [live,None,None]


def test_real_ac_snapshot_matches_schema_and_getter_never_runs_inference(modules,monkeypatch):
    signal, _, _ = modules
    observer=importlib.import_module('voice_vad_signal_observation')
    phase=importlib.import_module('voice_input_observation')
    fixture=runpy.run_path(str(ROOT/'tests/unit/development/test_voice_vad_signal_observation.py'))
    conn=fixture['connection'](fixture['provider']())
    original=phase._ObservedVAD.is_vad
    try:
        conn.vad=phase._ObservedVAD(conn.vad,phase._State())
        observer.install_voice_vad_signal_observation(type(conn),input_observation_module=phase)
        pcm=fixture['PCM']
        assert conn._decode_opus_packet(pcm)==pcm
        conn.vad.is_vad(conn,pcm)
        calls=conn.vad.original.session.original.calls
        raw=observer.voice_vad_signal_snapshot(conn)
        value=signal.snapshot(conn)
        assert tuple(observer.EXPORTED_COUNTS)==signal.COUNT_KEYS
        assert tuple(observer.PROBABILITY_EDGES)==signal.EDGES
        assert value==json.loads(json.dumps(raw)) and value['state']=='observed'
        value['groups']['speaking']['counts'][0]=12345
        assert signal.snapshot(conn)['groups']['speaking']['counts'][0]==1
        assert conn.vad.original.session.original.calls==calls
    finally:
        phase._ObservedVAD.is_vad=original


@pytest.mark.parametrize('bad', ['extra','bool_count','nan','unknown_stage','count_order','probability',
                                 'reference','missing_data','unknown_state','nested_text'])
def test_strict_numeric_projection_rejects_bad_optional_signal(modules,bad):
    signal, _, _ = modules
    value=maximum_signal(signal)
    phase=next(iter(signal.PHASES))
    if bad=='extra':value['private']='PRIVATE'
    elif bad=='bool_count':value['groups'][phase]['counts'][0]=True
    elif bad=='nan':value['groups'][phase]['energy']['vad_input']['max_rms_pcm16']=float('nan')
    elif bad=='unknown_stage':value['recent_groups'][phase]['energy']['PRIVATE']={}
    elif bad=='count_order':value['count_keys'][0]='PRIVATE'
    elif bad=='probability':value['groups'][phase]['probability']['bins'].append(0)
    elif bad=='reference':value['aec_reference']['timestamp']=123
    elif bad=='missing_data':value['state']='not_observed'
    elif bad=='unknown_state':value['state']=[]
    else:value['contract']['runtime_model_hash']='PRIVATE'
    result=signal.project(value)
    assert result==signal.missing('unavailable')
    assert 'PRIVATE' not in json.dumps(result)


def test_real_http_auth_exact_path_and_two_complete_bounded_responses(modules,monkeypatch,tmp_path):
    signal, device, http = modules
    from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient
    from longmemory.adapters.device_control.projections import device_status
    old=runpy.run_path(str(ROOT/'tests/fixtures/ai_signal_device_status_boundary.py'))['maximum_existing_status']()
    expected=device_status(old)
    control=device.DeviceControl('synthetic')
    control.status=lambda:deepcopy(old)
    calls=[]
    def get(_):calls.append(1);return maximum_signal(signal)
    monkeypatch.setitem(sys.modules,'voice_vad_signal_observation',NS(voice_vad_signal_snapshot=get))
    control.attach(NS(websocket=NS(state=NS(name='OPEN'))),'synthetic')
    async def run():
        headers={'Host':'127.0.0.1:12345','Authorization':'Bearer '+'a'*64}
        async with TestClient(TestServer(http.create_app(control,'a'*64,port=12345))) as client:
            for extra,status in (({'Authorization':'wrong'},401),({'Origin':'http://invalid'},403),
                                 ({'Sec-Fetch-Site':'same-origin'},403),({'Host':'invalid'},403)):
                async with client.get('/api/voice-input-signal',headers={**headers,**extra}) as response:
                    assert response.status==status
            assert not calls
            for method,path in (('POST','/api/voice-input-signal'),('HEAD','/api/voice-input-signal'),
                                ('GET','/api/voice-input-signal/'),('GET','/api/voice-input-signal-extra')):
                async with client.request(method,path,headers=headers) as response:
                    assert response.status in (404,405)
            assert not calls
            async with client.get('/api/voice-input-signal',headers=headers) as response:
                raw=await response.read()
                assert response.status==200 and len(raw)<=signal.MAX_BYTES<16384
                assert response.headers['Cache-Control']=='no-store'
                assert response.headers['X-Content-Type-Options']=='nosniff'
                assert json.loads(raw)==maximum_signal(signal)
            async with client.get('/api/device',headers=headers) as response:
                original=await response.read()
                assert original==json.dumps(old).encode() and len(original)==15519<16384
            class LocalSession:
                def request(self,method,url,**kwargs):
                    assert url.startswith('http://127.0.0.1:8766/')
                    kwargs['headers']['Host']=headers['Host']
                    # 仅改测试传输目的地，真实客户端流式16KiB检查原样执行。
                    return client.session.request(method,client.make_url(url.removeprefix('http://127.0.0.1:8766')),**kwargs)
            token=tmp_path/'synthetic-token';token.write_text('a'*64)
            bridge=XiaozhiControlClient(token);bridge._session=LocalSession()
            assert await bridge.status()==expected
            assert await bridge._request('GET','/api/voice-input-signal')==maximum_signal(signal)
            control.connections.clear()
            async with client.get('/api/voice-input-signal',headers=headers) as response:
                assert await response.json()==signal.missing('no_connection')
    asyncio.run(run())
