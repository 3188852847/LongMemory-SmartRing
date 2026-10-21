"""有限字段投影与真实随机环回HTTP；不连接日用端口或设备。"""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace as NS

import pytest
from aiohttp import ClientSession, web

from longmemory.adapters.device_control.projections import device_status
from longmemory.adapters.device_control.protocol import BridgeError
from longmemory.adapters.device_control.voice_interruption import COUNTERS, voice_interruption
from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'scripts/development/xiaozhi'


@pytest.fixture
def producer(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import voice_interruption as module
    return module


def sample(producer, *, observed=False):
    conn = NS(tts=NS(_longmemory_cosy_streaming_installed=True), sentence_id='synthetic',
        _longmemory_audio_revocation_installed=True, _longmemory_cosy_delivery_mode='adaptive')
    if observed:
        lease = producer.OutputLease(conn, 'synthetic', producing=True)
        lease.state.producer('adaptive_buffer', 'incremental', lease=lease)
        lease.state.note('first_answer_send_returned')
        lease.release()
    return producer.snapshot(conn)


@pytest.mark.parametrize('observed', [False, True])
def test_actual_snapshot_is_finite_detached_and_keeps_configuration_distinct(producer, observed):
    value = sample(producer, observed=observed)
    assert COUNTERS == frozenset(producer.COUNTERS)
    output = voice_interruption(value)
    assert output == value and len(json.dumps(output)) < 2400
    output['counts']['asr_handoff'] = 100
    assert value['counts']['asr_handoff'] == 0
    assert output['device_playback_acknowledged'] is False
    if observed:
        assert output['configuration']['delivery_mode'] == 'adaptive'
        assert output['observed']['request_delivery_mode'] == 'incremental'
        assert output['observed']['server_model_delivery_mode'] == 'unconfirmed'
    else:
        assert output['observed'] is None
    assert voice_interruption(producer.snapshot(None))['status'] == 'no_connection'


@pytest.mark.parametrize('field,bad', [
    ('version', True), ('version', 2), ('enabled', 1), ('epoch', True), ('epoch', -1),
    ('epoch', 9007199254740992), ('epoch', None), ('active_tts_calls', 1.5),
    ('status', 'ready'), ('device_playback_acknowledged', True),
    ('counts', {}), ('counts', {'private_text':'synthetic-secret'}),
    ('configuration', {'delivery_mode':'adaptive','value_kind':'observed'}),
    ('configuration', {'delivery_mode':[], 'value_kind':'configuration'}),
    ('observed', {'private_audio':'synthetic-secret'}),
    ('last_stage', {'event':'private_text','epoch':0,'at_ms':1}),
])
def test_malformed_optional_snapshot_is_rejected_without_echo(producer, field, bad):
    value = sample(producer)
    value[field] = bad
    with pytest.raises(BridgeError, match='^bridge_invalid_response$') as error:
        voice_interruption(value)
    assert error.value.status == 502


@pytest.mark.parametrize('change', [
    {'request_delivery_mode':'buffered'}, {'v2_transport_confirmed':1},
    {'server_model_delivery_mode':'adaptive'}, {'server_reply_cache_hit':True},
    {'private_text':'synthetic-secret'},
])
def test_observation_never_infers_server_mode_cache_or_accepts_extra_fields(producer, change):
    value = sample(producer, observed=True)
    value['observed'].update(change)
    with pytest.raises(BridgeError):
        voice_interruption(value)


def test_legacy_response_omits_increment_and_unknown_internal_data_is_not_forwarded():
    value = dict(connection_count=0,ready=False,read_volume_supported=False,set_volume_supported=False,
        announcement_supported=False,announcement_ready=False,user_session_active=False, private_text='synthetic-secret')
    output = device_status(value)
    assert 'voice_interruption' not in output and 'private_text' not in output


def test_random_http_guard_projection_readonly_and_disconnect_do_not_reuse_old_observation(producer, tmp_path):
    async def run():
        import control_http
        from device_control import DeviceControl
        bound = asyncio.Event(); bound.set()
        conn = NS(websocket=NS(state=NS(name='OPEN')), bind_completed_event=bound, need_bind=False,
            mcp_client=NS(ready=True,tools={}), features={'mcp':True}, tts=NS(_longmemory_cosy_streaming_installed=True),
            sentence_id='synthetic',_longmemory_audio_revocation_installed=True,
            _longmemory_cosy_delivery_mode='buffered')
        lease = producer.OutputLease(conn, 'synthetic')
        lease.state.producer('buffered_pcm','buffered',lease=lease)
        control = DeviceControl('synthetic-device')
        control.attach(conn,'synthetic-device')
        sock = socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        token='e'*64
        runner=web.AppRunner(control_http.create_app(control,token,port),access_log=None)
        session=ClientSession(trust_env=False)
        client=XiaozhiControlClient(tmp_path/'token')
        client.token_file.write_text(token)
        class PortSession:
            def request(self,method,url,**kwargs):
                assert url=='http://127.0.0.1:8766/api/device'
                assert kwargs['allow_redirects'] is False
                return session.request(method,f'http://127.0.0.1:{port}/api/device',**kwargs)
        client._session=PortSession()  # 仅测试会话改写目的地，永不连接日用8766。
        try:
            await runner.setup();await web.SockSite(runner,sock).start()
            url=f'http://127.0.0.1:{port}/api/device'
            auth={'Authorization':'Bearer '+token}
            for headers,code in [({},401),({**auth,'Origin':f'http://127.0.0.1:{port}'},403),({**auth,'Host':'bad.invalid'},403)]:
                async with session.get(url,headers=headers) as response:assert response.status==code
            before=deepcopy(producer.snapshot(conn))
            first=await client.status();second=await client.status()
            assert first['voice_interruption']==second['voice_interruption']==before
            assert producer.snapshot(conn)==before
            control.detach(conn)
            offline=await client.status()
            assert offline['ready'] is False
            assert offline['voice_interruption']==producer.snapshot(None)
            assert offline['voice_interruption']['observed'] is None
        finally:
            await session.close();await runner.cleanup();sock.close()
    asyncio.run(run())
