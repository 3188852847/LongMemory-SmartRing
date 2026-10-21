"""公共输入观测接线契约；仅模拟AC接口与服务，不导入模型或连接日用。"""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT/'scripts/development/xiaozhi'
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location('ai_input_bootstrap_test', DIRECTORY/'launch_with_memory.py')
    launch = importlib.util.module_from_spec(spec); spec.loader.exec_module(launch)
    spec = importlib.util.spec_from_file_location('ai_input_getter_test', DIRECTORY/'device_control.py')
    device = importlib.util.module_from_spec(spec); spec.loader.exec_module(device)
finally:
    sys.path.pop(0)


def snapshot(state='observed'):
    value = dict.fromkeys(('version','state','counts','inflight','queue_depth','current_flags',
        'last_handle_flags','endpoint_packet_count','endpoint_pcm_bytes','buffer_frames_before_receive',
        'formal_audio_frames','formal_pcm_bytes','counter_saturated','value_kind'))
    value.update(version=1,state=state,value_kind='connection_counters_not_audio_or_cpu_time')
    if state == 'observed':
        value.update(counts={'queue_put': 16},inflight={'route': 0},queue_depth=0,
                     current_flags={'client_aec': False},last_handle_flags={'client_aec': True},
                     endpoint_packet_count=16,endpoint_pcm_bytes=30720,counter_saturated=False)
    return value


def test_getter_projects_only_current_connection_and_does_not_cache_old_counts(monkeypatch):
    live, calls = object(), []
    def get(connection):
        calls.append(connection)
        return snapshot('no_connection' if connection is None else 'observed')
    monkeypatch.setitem(sys.modules,'voice_input_observation',SimpleNamespace(voice_input_observation_snapshot=get))
    assert device.voice_input_observation_diagnostics(live)['counts']=={'queue_put':16}
    disconnected=device.voice_input_observation_diagnostics()
    assert disconnected['state']=='no_connection' and disconnected['counts'] is None
    assert disconnected['current_flags'] is None and calls == [live,None]


@pytest.mark.parametrize('state',['not_observed','closed'])
def test_getter_preserves_missing_or_closed_state_without_inventing_observations(monkeypatch,state):
    monkeypatch.setitem(sys.modules,'voice_input_observation',SimpleNamespace(
        voice_input_observation_snapshot=lambda _:snapshot(state)))
    value=device.voice_input_observation_diagnostics(object())
    assert value['state']==state and value['endpoint_packet_count'] is None


@pytest.mark.parametrize('bad',['exception','new_private_field','wrong_version','oversize','non_json'])
def test_probe_failure_never_changes_status_or_leaks_private_values(monkeypatch,bad):
    value=snapshot()
    if bad=='new_private_field':value['transcript']='PRIVATE-CONTENT'
    elif bad=='wrong_version':value['version']=2
    elif bad=='oversize':value['counts']={'too_large':'PRIVATE'*4000}
    elif bad=='non_json':value['counts']={'bad':object()}
    def get(_):
        if bad=='exception':raise RuntimeError('PRIVATE-PATH')
        return value
    monkeypatch.setitem(sys.modules,'voice_input_observation',SimpleNamespace(voice_input_observation_snapshot=get))
    result=device.voice_input_observation_diagnostics(object())
    assert result['state']=='unavailable' and result['counts'] is None
    assert 'PRIVATE' not in json.dumps(result)


def test_bootstrap_uses_loaded_actual_provider_after_control_wrappers_before_accept(monkeypatch,tmp_path):
    calls=[]
    class Base:pass
    class Provider(Base):pass
    class Connection:pass
    class Server:
        _asr=Provider()
        async def start(self):calls.append('accept');return 'business-result'
    base=SimpleNamespace(ASRProviderBase=Base)
    receive=object()
    monkeypatch.setitem(sys.modules,'core.providers.asr.fun_local',SimpleNamespace(ASRProvider=Provider))
    monkeypatch.setitem(sys.modules,'control_compatibility',SimpleNamespace(
        verify_control_snapshot=lambda path: calls.append(('fingerprint',path))))
    def install(cls,base_module,receiver,*,asr_provider_classes):
        assert cls is Connection and base_module is base and receiver is receive
        assert asr_provider_classes == (Provider,)
        assert Connection.latest_wrapper=='control'
        Connection.input_ready=True
        calls.append('probe')
    def signal(cls):
        assert cls is Connection and cls.input_ready and cls.latest_wrapper=='control'
        calls.append('signal')
    monkeypatch.setitem(sys.modules,'voice_input_observation',SimpleNamespace(install_voice_input_observation=install))
    monkeypatch.setitem(sys.modules,'voice_vad_signal_observation',SimpleNamespace(install_voice_vad_signal_observation=signal))
    launch.install_voice_input_observation_policy(Server,Connection,base,receive,upstream_root=tmp_path)
    first=Server.start
    launch.install_voice_input_observation_policy(Server,Connection,base,receive,upstream_root=tmp_path)
    assert Server.start is first
    original=Server.start
    async def control(server):
        Connection.latest_wrapper='control';calls.append('control');return await original(server)
    Server.start=control
    assert asyncio.run(Server().start())=='business-result'
    assert calls==[('fingerprint',tmp_path),'control','probe','signal','accept']


@pytest.mark.parametrize('failure',['unknown_fingerprint','unknown_provider','installer_exception','signal_installer_exception'])
def test_unreviewed_or_failed_diagnostic_keeps_original_business_start(monkeypatch,tmp_path,failure):
    calls=[]
    class Base:pass
    class Provider(Base):pass
    class Other(Base):pass
    class Connection:pass
    class Server:
        _asr=Other() if failure=='unknown_provider' else Provider()
        async def start(self):calls.append('business');return 17
    def verify(_):
        if failure=='unknown_fingerprint':raise ValueError('changed')
    def install(*_args,**_kwargs):
        calls.append('probe')
        if failure=='installer_exception':raise RuntimeError('PRIVATE')
    def signal(*_args):
        calls.append('signal');raise RuntimeError('PRIVATE')
    monkeypatch.setitem(sys.modules,'control_compatibility',SimpleNamespace(verify_control_snapshot=verify))
    monkeypatch.setitem(sys.modules,'core.providers.asr.fun_local',SimpleNamespace(ASRProvider=Provider))
    monkeypatch.setitem(sys.modules,'voice_input_observation',SimpleNamespace(install_voice_input_observation=install))
    monkeypatch.setitem(sys.modules,'voice_vad_signal_observation',SimpleNamespace(install_voice_vad_signal_observation=signal))
    launch.install_voice_input_observation_policy(Server,Connection,SimpleNamespace(ASRProviderBase=Base),
                                                 object(),upstream_root=tmp_path)
    assert asyncio.run(Server().start())==17
    expected={'installer_exception':['probe','business'],
              'signal_installer_exception':['probe','signal','business']}
    assert calls == expected.get(failure,['business'])


def test_real_ac_helper_bootstrap_prefetch_alias_and_public_projection(monkeypatch,tmp_path):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    import voice_input_observation as observer
    import voice_input_interruption_probe as probe
    from longmemory.adapters.device_control.projections import device_status
    from longmemory.adapters.device_control.voice_input_observation import COUNTERS
    assert COUNTERS==frozenset(observer.COUNTERS)
    async def run():
        h=probe.harness(speaking=True,prefetch=True)
        base_cls=h.upstream.ASRProviderBase
        async def unused(*_):return None
        async def open_audio(_provider,connection):
            assert isinstance(connection.asr_audio_queue,observer._ObservedQueue)
        base_cls.handle_voice_stop=unused
        base_cls.open_audio_channels=open_audio
        base=SimpleNamespace(ASRProviderBase=base_cls,handleAudioMessage=h.upstream.handleAudioMessage)
        class Server:
            _asr=h.provider
            async def start(self):
                await h.provider.open_audio_channels(h.connection)
                return 'original-start'
        monkeypatch.setitem(sys.modules,'control_compatibility',SimpleNamespace(verify_control_snapshot=lambda _:None))
        monkeypatch.setitem(sys.modules,'core.providers.asr.fun_local',SimpleNamespace(ASRProvider=type(h.provider)))
        launch.install_voice_input_observation_policy(Server,type(h.connection),base,h.upstream,upstream_root=tmp_path)
        try:
            assert await Server().start()=='original-start'
            await h.connection._route_message(b'private-synthetic-input-not-exported')
            assert h.connection.asr_audio_queue.get_nowait() is probe.PCM
            h.connection.asr_audio=[probe.PCM]*15
            h.connection.client_have_voice=h.connection.client_voice_stop=True
            await h.provider.receive_audio(h.connection,probe.PCM,False)
            value=device.voice_input_observation_diagnostics(h.connection)
            assert value['counts']['queue_put']==value['counts']['queue_get']==1
            assert value['counts']['formal_begin']==value['counts']['speech_begin']==1
            assert value['counts']['result_nonempty']==1
            assert value['endpoint_packet_count']==16 and value['endpoint_pcm_bytes']==30720
            assert value['formal_audio_frames']==1 and value['formal_pcm_bytes']==30720
            payload=dict(connection_count=1,ready=True,read_volume_supported=False,set_volume_supported=False,
                announcement_supported=False,announcement_ready=False,user_session_active=True,
                voice_input_observation=value)
            projected=device_status(payload)['voice_input_observation']
            assert projected==value and 'private' not in json.dumps(projected)
            await probe.stop(h)
            assert device.voice_input_observation_diagnostics(h.connection)['state']=='closed'
            assert device.voice_input_observation_diagnostics()['counts'] is None
        finally:
            await probe.stop(h)
    asyncio.run(run())


MAIN=ROOT.parents[2] if ROOT.parent.name=='worktrees' else ROOT
VOICE_PYTHON=MAIN/'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe'


@pytest.mark.skipif(not VOICE_PYTHON.is_file(),reason='owner-installed Python 3.10 input observer runtime unavailable')
def test_actual_python310_timeout_is_classified_without_changing_original_exception():
    code=r'''
import asyncio,json,sys,threading
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
import voice_input_observation as o
async def run():
 c=SimpleNamespace(stop_event=threading.Event()); errors=[]
 async def original(*a,**k):
  try: await asyncio.wait_for(asyncio.Event().wait(),.01)
  except BaseException as error: errors.append(error);raise
 token=o._FORMAL.set(c)
 try:
  try: await o._speech_wrapper(original)(object())
  except BaseException as error:
   assert error is errors[0]
   assert isinstance(error,asyncio.TimeoutError) and not isinstance(error,TimeoutError)
  else:raise AssertionError('missing real wait_for timeout')
 finally:o._FORMAL.reset(token)
 s=o.voice_input_observation_snapshot(c)
 assert s['counts']['speech_timeout']==1 and s['counts']['speech_error']==0 and not any(s['inflight'].values())
 print(json.dumps(dict(python=sys.version.split()[0],speech_timeout=1,original_exception_preserved=True,torch_imported='torch' in sys.modules)))
asyncio.run(run())
'''
    r=subprocess.run([str(VOICE_PYTHON),'-I','-B','-X','utf8','-c',code,str(DIRECTORY)],
        capture_output=True,timeout=10,cwd=ROOT)
    assert r.returncode==0,r.stderr.decode('utf-8',errors='replace')[-1200:]
    value=json.loads(r.stdout)
    assert value==dict(python='3.10.20',speech_timeout=1,original_exception_preserved=True,torch_imported=False)
