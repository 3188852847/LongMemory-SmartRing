"""模式配置、AD有限摘要与整包预算；不启动服务、模型或真实设备。"""

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace as NS

import pytest

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts/development/launcher'))
    monkeypatch.syspath_prepend(str(ROOT/'scripts/development/xiaozhi'))
    return tuple(importlib.import_module(name) for name in ('cosy_status','cosyvoice_delivery','runtime','device_control'))


def observation(ad, *, blocked=False, mode='incremental'):
    session=ad.DeliverySession(mode)
    session.degrade('reader_cleanup_unconfirmed' if blocked else 'after_handoff',blocked=blocked)
    session.note('failed',handoff=True,cleanup='unconfirmed' if blocked else 'confirmed')
    session.outcomes=dict.fromkeys(ad.OUTCOMES,1000000)
    return session.snapshot(mode)


def test_all_three_consumers_share_one_bounded_contract_and_do_not_promote_playback(modules):
    status,ad,_,device=modules
    from longmemory.adapters.device_control.cosy_delivery import cosy_delivery
    values=[ad.delivery_snapshot(None),ad.delivery_snapshot(NS()),observation(ad),observation(ad,blocked=True)]
    for value in values:
        assert status.project_observation(value)==device.project_cosy_delivery(value)==cosy_delivery(value)==value
        assert value['physical_playback_verified'] is False
    # 未观测到session时effective字段只是配置；UI必须根据not_observed另行显示待确认。
    assert values[1]['state']=='not_observed'


@pytest.mark.parametrize('bad',['private','count','physical','append','unknown_mode','unknown_reason','cleanup','old_counts'])
def test_bad_optional_summary_is_unknown_without_leaking_or_changing_other_fields(modules,bad):
    status,ad,_,_=modules
    from longmemory.adapters.device_control.cosy_delivery import cosy_delivery
    value=observation(ad,blocked=True)
    if bad=='private':value['text']='PRIVATE'
    elif bad=='count':value['outcomes']['completed']=True
    elif bad=='physical':value['physical_playback_verified']=True
    elif bad=='append':value['next_segment_allowed']=True
    elif bad=='unknown_mode':value['effective_mode']='PRIVATE'
    elif bad=='unknown_reason':value['failure_code']='PRIVATE'
    elif bad=='cleanup':value.update(state='configured',restart_required=False,effective_mode='incremental')
    else:value=ad.delivery_snapshot(None);value['outcomes']['failed']=1
    assert status.project_observation(value) is None and cosy_delivery(value) is None


def test_getter_reads_only_loaded_ad_and_current_connection_with_no_creation(modules,monkeypatch):
    _,ad,_,device=modules
    calls=[]
    def get(conn):calls.append(conn);return ad.delivery_snapshot(conn)
    monkeypatch.setitem(sys.modules,'voice_latency',NS(delivery_snapshot=get))
    control=device.DeviceControl('synthetic')
    conn=NS(websocket=NS(state=NS(name='OPEN')))
    control.attach(conn,'synthetic')
    result=control.status()
    assert result['cosy_delivery']['state']=='not_observed' and vars(conn)=={'websocket':conn.websocket}
    control.detach(conn)
    assert control.status()['cosy_delivery']['state']=='no_connection'
    assert calls==[conn,None]
    monkeypatch.setitem(sys.modules,'voice_latency',NS(delivery_snapshot=lambda _: (_ for _ in ()).throw(ValueError('PRIVATE'))))
    assert 'cosy_delivery' not in control.status()


def test_planned_startup_and_connection_failure_remain_distinct(modules):
    status,ad,_,_=modules
    settings=dict(voice=True,voice_mode='pipeline',tts_backend='cosyvoice3',cosy_delivery_mode='adaptive')
    manager=NS(services={'voice':object()},cosy_startup_mode='incremental',cosy_startup_source='preference',
               current_cosy_delivery=lambda:observation(ad))
    value=status.launcher_summary(manager,settings,{})
    assert value['next_start_mode']=='adaptive' and value['startup_mode']=='incremental'
    assert value['observation']['effective_mode']=='buffered' and value['restart_required']
    value=status.launcher_summary(manager,settings,{'LONGMEMORY_COSY_DELIVERY_MODE':'incremental'})
    assert value['next_start_mode']=='incremental' and value['next_start_source']=='environment'
    assert not value['restart_required'] and settings['cosy_delivery_mode']=='adaptive'
    manager.current_cosy_delivery=lambda:observation(ad,blocked=True)
    blocked=status.launcher_summary(manager,settings,{})
    assert blocked['observation']['effective_mode'] is None and not blocked['observation']['next_segment_allowed']
    assert blocked['restart_required']
    invalid=status.launcher_summary(manager,settings,{'LONGMEMORY_COSY_DELIVERY_MODE':'PRIVATE'})
    assert not invalid['selection_valid'] and invalid['next_start_mode'] is None and 'PRIVATE' not in json.dumps(invalid)
    manager.current_cosy_delivery=lambda: (_ for _ in ()).throw(ValueError('PRIVATE'))
    assert status.launcher_summary(manager,settings,{})['observation'] is None
    manager.services={}
    assert status.launcher_summary(manager,settings,{})['startup_mode'] is None


def test_cached_observation_expires_or_disappears_with_owned_process(modules,monkeypatch):
    _,ad,runtime,_=modules
    manager=runtime.Manager();exited=[None]
    manager.services={'voice':NS(process=NS(poll=lambda:exited[0]))}
    manager._cosy_delivery_observation=observation(ad)
    manager._cosy_delivery_observed_at=9
    monkeypatch.setattr(runtime,'time',NS(monotonic=lambda:10))
    first=manager.current_cosy_delivery();assert first['effective_mode']=='buffered'
    first['outcomes']['completed']=0
    assert manager.current_cosy_delivery()['outcomes']['completed']==1000000
    exited[0]=0
    assert manager.current_cosy_delivery() is None
    exited[0]=None;manager._cosy_delivery_observed_at=7.9
    assert manager.current_cosy_delivery() is None


def test_complete_device_maximum_with_saturated_ad_snapshot_keeps_existing_16k_limit(modules,tmp_path):
    status,ad,_,_=modules
    from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient
    old=runpy.run_path(str(ROOT/'tests/fixtures/ai_signal_device_status_boundary.py'))['maximum_existing_status']()
    assert len(json.dumps(old).encode())==15519
    for blocked in (False,True):
        value=deepcopy(old);value['cosy_delivery']=observation(ad,blocked=blocked)
        assert len(json.dumps(value['cosy_delivery']).encode())<=512
        raw=json.dumps(value).encode();assert len(raw)<16384
        class Response:
            status=200
            content=None
            def __init__(self):self.content=self
            async def __aenter__(self):return self
            async def __aexit__(self,*_):pass
            async def iter_chunked(self,size):
                for start in range(0,len(raw),17):yield raw[start:start+17]
        class Session:
            def request(self,*args,**kwargs):return Response()
        token=tmp_path/'synthetic-token';token.write_text('a'*64)
        client=XiaozhiControlClient(token);client._session=Session()
        result=asyncio.run(client.status())
        assert result['voice_input_observation']==old['voice_input_observation']
        assert result['voice_latency']==old['voice_latency']
        assert result['cosy_delivery']==value['cosy_delivery']
