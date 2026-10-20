"""同声线缓存、早等待、取消与答案优先；全部是合成包/注入时钟，无模型或TTS。"""

import asyncio
import json
from pathlib import Path
from queue import Queue
import struct
import sys
import threading
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts/development/xiaozhi'))
import voice_waiting as w
import voice_latency as latency
import cosyvoice_profiles as profiles
import prepare_voice_waiting as prepare


def blob(value=b'cue'):
    return b'LMWAIT01'+struct.pack('!H',len(value))+value


def blobs(value=b'cue'):
    return {f'{k}-{r}':blob(value) for k in w.PHRASES for r in (16000,24000)}


class Timer:
    created=[]
    def __init__(self, delay, callback):
        self.delay,self.callback,self.cancelled=delay,callback,False
        self.created.append(self)
    def start(self):pass
    def cancel(self):self.cancelled=True
    def fire(self):
        if not self.cancelled:self.callback()


def connection(monkeypatch,tmp_path):
    Timer.created=[]
    monkeypatch.setattr(w.threading,'Timer',Timer)
    monkeypatch.setitem(sys.modules,'core.providers.tts.dto.dto',NS(SentenceType=NS(MIDDLE='middle')))
    monkeypatch.setattr(w,'CACHE_ROOT',tmp_path/'cache')
    monkeypatch.setattr(w,'_voice_context',lambda:{'identity':'a'*64,'default':False})
    w.publish_cache(w.CACHE_ROOT,'a'*64,blobs())
    now=[0.0]
    monkeypatch.setattr(w,'time',NS(perf_counter=lambda:now[0]))
    c=NS(sentence_id='old',stop_event=threading.Event(),client_abort=False,sample_rate=16000,
        _longmemory_waiting_enabled=True,tts=NS(tts_audio_queue=Queue()),
        config={'selected_module':{'TTS':'CustomTTS'},'TTS':{'CustomTTS':{'url':'http://127.0.0.1:18770/v1/audio/speech'}}},
        logger=NS(bind=lambda **kw:NS(info=lambda *a:None)))
    c._longmemory_voice_latency=latency.VoiceLatencyTracker(c,clock=lambda:now[0])
    c._longmemory_voice_latency.begin();c.sentence_id='current'
    c._longmemory_voice_latency.bind_sentence()
    return c,now


@pytest.mark.parametrize('default',[False,True])
def test_both_voice_modes_require_current_phrase_cache(monkeypatch,tmp_path,default):
    monkeypatch.setattr(w,'CACHE_ROOT',tmp_path/'cache')
    monkeypatch.setattr(w,'_voice_context',lambda:{'identity':'a'*64,'default':default})
    assert w.load_packets('model',16000)==w.load_packets('web',24000)==()
    assert not w.CACHE_ROOT.exists()  # 问话路径不写缓存，不调用任何合成。
    w.publish_cache(w.CACHE_ROOT,'a'*64,blobs())
    assert w.load_packets('model',16000)==w.load_packets('web',24000)==(b'cue',)
    monkeypatch.setattr(w,'_voice_context',lambda:{'identity':'b'*64,'default':False})
    assert w.load_packets('model',16000)==w.load_packets('web',24000)==()


@pytest.mark.parametrize('damage',['digest','voice','phrase','engine','codec','partial','json'])
def test_invalid_cache_is_quiet_and_not_repaired(tmp_path,damage):
    identity='a'*64;w.publish_cache(tmp_path,identity,blobs())
    path=tmp_path/identity[:16]/'manifest.json';m=json.loads(path.read_text())
    if damage=='digest':m['items']['model-16000']['sha256']='b'*64
    elif damage=='voice':m['voice_identity']='b'*64
    elif damage=='phrase':m['items']['model-16000']['phrase_sha256']='b'*64
    elif damage=='engine':m['engine']='cosyvoice3/Fun-CosyVoice3-0.5B-2512/opus60-v1'
    elif damage=='codec':m['codec']='opus-mono-20ms'
    elif damage=='partial':del m['items']['web-24000']
    else:m=[]
    path.write_text(json.dumps(m));before=path.read_bytes()
    assert w.cached_packets(tmp_path,identity,'model',16000)==()
    assert path.read_bytes()==before


def test_manifest_failure_preserves_last_complete_cache(tmp_path,monkeypatch):
    identity='a'*64;w.publish_cache(tmp_path,identity,blobs(b'old'))
    original=Path.replace
    def fail(path,target):
        if Path(target).name=='manifest.json':raise OSError('synthetic publication interruption')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',fail)
    with pytest.raises(OSError):w.publish_cache(tmp_path,identity,blobs(b'new'))
    assert w.cached_packets(tmp_path,identity,'model',16000)==(b'old',)
    assert not list(tmp_path.rglob('*.tmp'))


def test_explicit_maintenance_required_before_importing_model_dependencies(tmp_path):
    with pytest.raises(ValueError,match='maintenance_window'):
        prepare.main(['--prepare','--server-dir',str(tmp_path)])
    prepare.main([])


def test_wrong_workspace_without_selected_profile_cannot_prepare_default_voice(tmp_path,monkeypatch):
    monkeypatch.setattr(prepare,'profile_store',lambda:NS(profile_path=tmp_path/'missing-profile.json'))
    with pytest.raises(ValueError,match='selected_profile_missing'):
        prepare.main(['--prepare','--maintenance-window','--server-dir',str(tmp_path)])


def test_prepare_snapshot_identity_publish_and_cache_hit(tmp_path):
    calls=[];encodes=[];store=NS(model_context=lambda:({'style':'synthetic-style'},None,'a'*64))
    synth=lambda text,profile:(calls.append((text,dict(profile))) or b'synthetic-wav')
    encode=lambda data,rate:(encodes.append((data,rate)) or blob(str(rate).encode()))
    result=prepare.prepare_cache(store,synth,encode,root=tmp_path)
    assert result['status']=='ready' and result['items']==4
    assert calls==[('稍等。',{'style':'synthetic-style'})]
    assert encodes==[(b'synthetic-wav',16000),(b'synthetic-wav',24000)]
    assert all(profile['style']=='synthetic-style' for _,profile in calls)
    for rate in (16000,24000):
        assert w.cached_packets(tmp_path,result['voice_identity'],'model',rate)==w.cached_packets(
            tmp_path,result['voice_identity'],'web',rate)==(str(rate).encode(),)
    def forbidden(*args):raise AssertionError('cache hit must not call TTS')
    assert prepare.prepare_cache(store,forbidden,forbidden,root=tmp_path)['status']=='already_ready'


def test_recipe_change_keeps_old_cache_and_changes_identity(tmp_path,monkeypatch):
    current=profiles.WAITING_ENGINE
    monkeypatch.setattr(profiles,'WAITING_ENGINE','cosyvoice3/Fun-CosyVoice3-0.5B-2512/opus60-v1')
    old=profiles.waiting_identity('a'*64)
    monkeypatch.setitem(w.PHRASES,'model','我想一下。')
    monkeypatch.setitem(w.PHRASES,'web','我查一下。')
    w.publish_cache(tmp_path,old,blobs(b'old'))
    before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monkeypatch.setattr(profiles,'WAITING_ENGINE',current)
    monkeypatch.setitem(w.PHRASES,'model','稍等。')
    monkeypatch.setitem(w.PHRASES,'web','稍等。')
    new=profiles.waiting_identity('a'*64)
    assert new!=old
    assert w.cached_packets(tmp_path,old,'model',16000)==()
    result=prepare.prepare_cache(NS(model_context=lambda:({},None,'a'*64)),
        lambda *args:b'new',lambda *args:blob(b'new'),root=tmp_path)
    assert result['voice_identity']==new
    assert all(p.read_bytes()==data for p,data in before.items())


def test_complete_waveform_guard_never_trims_silence_or_words():
    import numpy as np
    audio=np.zeros(33600,dtype=np.float32)  # 完整2.1秒，含首尾低电平。
    audio[8000:16000]=0.2
    before=audio.copy()
    prepare.validate_waveform(audio,16000)
    assert np.array_equal(audio,before)
    for values in (np.pad(audio,(0,1)),np.pad(audio,(10400,10400))):
        before=values.copy()
        with pytest.raises(ValueError,match='phrase_too_long'):
            prepare.validate_waveform(values,16000)
        assert np.array_equal(values,before)
    for values in (np.array([]),np.array([float('nan')]),np.array([float('inf')])):
        with pytest.raises(ValueError,match='samples_invalid'):
            prepare.validate_waveform(values,16000)
    with pytest.raises(ValueError,match='format_invalid'):
        prepare.validate_waveform(np.zeros((5,2)),16000)


@pytest.mark.parametrize('failure',['overlong','damaged','waveform_too_long'])
def test_failed_preparation_preserves_previous_cache_without_retry(tmp_path,failure):
    import numpy as np
    store=NS(model_context=lambda:({},None,'a'*64));identity=profiles.waiting_identity('a'*64)
    # 旧清单的文案不匹配使本次需要准备，失败后也不得覆盖它。
    w.publish_cache(tmp_path,identity,blobs(b'old'))
    path=tmp_path/identity[:16]/'manifest.json';manifest=json.loads(path.read_text())
    manifest['items']['web-24000']['phrase_sha256']='b'*64
    path.write_text(json.dumps(manifest))
    before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()};calls=[]
    def encode(*args):
        if failure=='waveform_too_long':
            prepare.validate_waveform(np.zeros(54400),16000)  # 3.4秒静音也拒绝。
        return blob()*36 if failure=='damaged' else b'LMWAIT01'+blob()[8:]*36
    with pytest.raises(ValueError,match='encoded_audio_invalid|phrase_too_long'):
        prepare.prepare_cache(store,lambda *args:(calls.append(1) or b'full-wav'),encode,root=tmp_path)
    assert calls==[1]
    assert {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before


def test_prepare_voice_drift_does_not_publish_partial_cache(tmp_path):
    identity=['a'*64];store=NS(model_context=lambda:({},None,identity[0]))
    def synth(*args):identity[0]='b'*64;return b'fake'
    with pytest.raises(ValueError,match='voice_changed'):
        prepare.prepare_cache(store,synth,lambda *a:blob(),root=tmp_path/'cache')
    assert not (tmp_path/'cache').exists()


def test_voice_context_reuses_checked_reference_until_identity_files_change(tmp_path,monkeypatch):
    path=tmp_path/'profile.json';path.write_text('synthetic-v1')
    wav=tmp_path/'ref.wav';wav.write_bytes(b'synthetic-not-real-audio')
    wav.with_suffix('.json').write_text('{}')
    calls=[];digest=['a'*64]
    def model_context():calls.append(1);return {'reference_id':'synthetic','style':''},wav,digest[0]
    store=NS(root=tmp_path,profile_path=path,model_context=model_context)
    monkeypatch.setattr(profiles,'profile_store',lambda:store)
    monkeypatch.setattr(profiles,'_waiting_cached',None)
    first=profiles.waiting_context()
    assert profiles.waiting_context()==first and len(calls)==1
    digest[0]='b'*64;path.write_text('synthetic-v2-longer')
    assert profiles.waiting_context()['identity']!=first['identity'] and len(calls)==2
    wav.write_bytes(b'changed-synthetic-reference')
    profiles.waiting_context();assert len(calls)==3


def test_missing_selected_profile_never_turns_into_default_waiting_voice(tmp_path,monkeypatch):
    def forbidden():raise AssertionError('missing profile must not resolve default context')
    monkeypatch.setattr(profiles,'profile_store',lambda:NS(root=tmp_path,
        profile_path=tmp_path/'missing.json',model_context=forbidden))
    assert profiles.waiting_context() is None


def test_short_path_collision_and_corrupt_blob_fail_closed(tmp_path):
    identity='a'*64;w.publish_cache(tmp_path,identity,blobs())
    with pytest.raises(ValueError,match='existing_identity'):
        w.publish_cache(tmp_path,'a'*16+'b'*48,blobs(b'other voice'))
    m=json.loads((tmp_path/identity[:16]/'manifest.json').read_text())
    p=tmp_path/identity[:16]/w._blob_name('model-16000',m['items']['model-16000']['sha256'])
    p.write_bytes(p.read_bytes()[:-1]+b'x')
    assert w.cached_packets(tmp_path,identity,'model',16000)==()


def test_memory_waiting_starts_before_query_and_reuses_one_timer(monkeypatch,tmp_path):
    c,now=connection(monkeypatch,tmp_path)
    async def query(text):
        assert len(Timer.created)==1
        now[0]=1.0;Timer.created[0].fire()
        assert c.tts.tts_audio_queue.qsize()==1
        now[0]=1.5;return 'synthetic evidence'
    c.memory=NS(query_memory=query)
    latency._observe_memory_waiting(c)
    assert asyncio.run(c.memory.query_memory('synthetic question'))=='synthetic evidence'
    old=c._longmemory_waiting
    w.begin_waiting(c,[]);Timer.created[0].fire()
    assert c._longmemory_waiting is old and len(Timer.created)==1 and c.tts.tts_audio_queue.qsize()==1
    assert c._longmemory_voice_latency.stage_snapshot()['timings_ms']['memory_returned_ms']==1500
    assert c._longmemory_voice_latency.snapshot()['timings_ms']['memory_ready_ms']==1500


@pytest.mark.parametrize('phase',['memory','model','tts'])
def test_slow_phase_gets_feedback_but_never_fakes_answer_timing(monkeypatch,tmp_path,phase):
    c,now=connection(monkeypatch,tmp_path)
    sent=[]
    async def sender(conn,packet,flow):sent.append(bytes(packet))
    module=NS(_do_send_audio=sender);w.install_waiting_sender(module)
    def advance(stage):
        now[0]+=1.0 if phase==stage else 0.1
        if now[0]>=0.9:Timer.created[0].fire()
    def send_feedback():
        if not c.tts.tts_audio_queue.empty():
            packet=c.tts.tts_audio_queue.get_nowait()[1][0]
            asyncio.run(module._do_send_audio(c,packet,{}))
    async def query(text):advance('memory');return 'synthetic evidence'
    c.memory=NS(query_memory=query);latency._observe_memory_waiting(c)
    asyncio.run(c.memory.query_memory('synthetic question'));send_feedback()
    w.begin_waiting(c,None);state=c._longmemory_waiting
    c._longmemory_voice_latency.mark('llm_requested_ms')
    advance('model');send_feedback()
    list(latency._observe_generator(c,iter(['synthetic output']),state))
    c._longmemory_voice_latency.begin_tts_segment(sentence_id=c.sentence_id)
    advance('tts');send_feedback()
    assert state.first_feedback_ms=={'memory':1000,'model':1100,'tts':1200}[phase]
    assert state.first_answer_ms is None
    assert c._longmemory_voice_latency.snapshot()['timings_ms']['first_audio_sent_ms'] is None
    w.mark_answer_ready(c)
    asyncio.run(module._do_send_audio(c,w.AnswerPacket(b'answer',state),{}))
    assert state.first_answer_ms==1200
    assert c._longmemory_voice_latency.snapshot()['timings_ms']['first_audio_sent_ms']==1200


def test_memory_failure_cancels_waiting_without_changing_error_or_archival_semantics(monkeypatch,tmp_path):
    c,now=connection(monkeypatch,tmp_path)
    async def query(text):raise RuntimeError('synthetic memory failure')
    c.memory=NS(query_memory=query);latency._observe_memory_waiting(c)
    with pytest.raises(RuntimeError,match='synthetic memory failure'):
        asyncio.run(c.memory.query_memory('synthetic'))
    assert c._longmemory_waiting.closed and Timer.created[0].cancelled
    Timer.created[0].fire();assert c.tts.tts_audio_queue.empty()


def test_first_tool_delta_is_not_reported_as_first_answer_text(monkeypatch,tmp_path):
    c,now=connection(monkeypatch,tmp_path)
    def responses():
        now[0]=0.2;yield '',[{'synthetic_tool':True}]
        now[0]=0.4;yield 'synthetic answer',[]
    list(latency._observe_generator(c,responses()))
    assert c._longmemory_voice_latency.snapshot()['timings_ms']['llm_first_output_ms']==200
    stages=c._longmemory_voice_latency.stage_snapshot()['timings_ms']
    assert stages['model_first_text_ms']==400
    assert c._longmemory_voice_latency.snapshot()['timings_ms']['first_audio_sent_ms'] is None


def test_fast_answer_cancel_missing_cache_and_voice_switch(monkeypatch,tmp_path):
    c,now=connection(monkeypatch,tmp_path)
    w.begin_waiting(c,None);w.mark_answer_ready(c);Timer.created[0].fire()
    assert c.tts.tts_audio_queue.empty()
    c.sentence_id='next';w.begin_waiting(c,None)
    monkeypatch.setattr(w,'_voice_context',lambda:{'identity':'b'*64,'default':False})
    Timer.created[-1].fire()
    assert c._longmemory_waiting.cue_state=='unavailable' and c.tts.tts_audio_queue.empty()
    c.sentence_id='third';w.begin_waiting(c,None);Timer.created[-1].fire()
    assert c._longmemory_waiting.cue_state=='unavailable' and c.tts.tts_audio_queue.empty()


@pytest.mark.parametrize('cancel',['abort','stop','new_turn','close'])
def test_late_packets_never_escape_after_cancellation(monkeypatch,tmp_path,cancel):
    c,now=connection(monkeypatch,tmp_path);w.begin_waiting(c,None);state=c._longmemory_waiting
    if cancel=='abort':c.client_abort=True
    elif cancel=='stop':c.stop_event.set()
    elif cancel=='new_turn':c.sentence_id='new'
    else:state.cancel()
    async def forbidden(*args):raise AssertionError('late packet escaped')
    module=NS(_do_send_audio=forbidden);w.install_waiting_sender(module)
    asyncio.run(module._do_send_audio(c,w.WaitingPacket(b'late',state),{}))
    asyncio.run(module._do_send_audio(c,w.AnswerPacket(b'late answer',state),{}))


def test_discarded_queue_frames_do_not_consume_virtual_playback_slots(monkeypatch,tmp_path):
    c,now=connection(monkeypatch,tmp_path);w.begin_waiting(c,None);state=c._longmemory_waiting
    callbacks=[];sent=[]
    controller=NS(frame_duration=60,play_position=0,start_sending=lambda callback:callbacks.append(callback))
    def start(conn,controller,flow):controller.start_sending(lambda packet:send(conn,packet,flow))
    async def send(conn,packet,flow):sent.append(bytes(packet))
    module=NS(_do_send_audio=send,_start_background_sender=start);w.install_waiting_sender(module)
    module._start_background_sender(c,controller,{'sentence_id':c.sentence_id})
    w.mark_answer_ready(c)
    for _ in range(20):
        controller.play_position+=60  # 固定上游在 callback 前占用这一帧。
        asyncio.run(callbacks[0](w.WaitingPacket(b'cue-tail',state)))
    controller.play_position+=60
    asyncio.run(callbacks[0](w.AnswerPacket(b'answer',state)))
    assert controller.play_position==60 and sent==[b'answer']
