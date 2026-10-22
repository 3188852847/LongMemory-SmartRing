"""复用既有固定SDK/真实WebSocket夹具；注入VAD仅证明控制流，不证明声学。"""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("existing_wire_cases", Path(__file__).with_name("test_voice_output_protocol_ws.py"))
WIRE_CASES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WIRE_CASES)

# 沿用既有真实固定SDK、撤权/输出代理和随机回环；只加原启动器已经安装的层。
PREFIX = WIRE_CASES.DRIVER.split("async def main():")[0]
ANCHOR = " guard.install_voice_interruption(u.Connection,u.receive,u.asr,u.send,tts_base_module=u.ttsbase)"
assert PREFIX.count(ANCHOR) == 1
PREFIX = PREFIX.replace(ANCHOR, '''
 from launch_with_memory import install_internal_end_prompt_boundary
 from voice_persistent_session import install_persistent_device_session
 u.Connection._check_timeout=lambda self:asyncio.Event().wait()
 install_internal_end_prompt_boundary(u.receive)
 install_persistent_device_session(u.Connection,u.receive)
 prior_seam=u.receive.no_voice_close_connect
 async def seam(conn,have_voice):
  getattr(conn,'test_events',[]).append('prior_seam')
  return await prior_seam(conn,have_voice)
 u.receive.no_voice_close_connect=seam
 u.asr.handleAudioMessage=u.receive.handleAudioMessage
''' + ANCHOR)

CASES = r'''
async def eos(u):
 await u.send.send_tts_message(u.conn,'start');await u.next()
 await u.send._do_send_audio(u.conn,b'pending-tail',{'sentence_id':'old','packet_count':0})
 assert await u.next()==b'pending-tail'
 await u.send.send_tts_message(u.conn,'stop');assert json.loads(await u.next())['state']=='stop'
 p=getattr(u.conn,wire.ATTRIBUTE)
 assert not u.conn.client_is_speaking and p.has_interrupt_target() and p.turn.eos
 assert u.consumer.queue==[b'pending-tail']  # 消费者合同预言机；不是设备播放ACK。
 return p

def bind_input(u,voiced=True):
 c=u.conn;p=getattr(c,wire.ATTRIBUTE);c.test_events=[];c.client_aec=True
 class VAD:
  calls=0
  def is_vad(self,conn,frame):self.calls+=1;c.test_events.append('vad');return voiced
 c.vad=VAD()
 async def receive(conn,frame,have_voice):
  assert have_voice is voiced;c.test_events.append('asr_receive')
 c.asr=NS(receive_audio=receive)
 raw=p.raw.send
 async def sent(value):
  result=await raw(value)
  if isinstance(value,str) and json.loads(value).get('state')=='interrupt':c.test_events.append('interrupt_return')
  return result
 p.raw.send=sent
 return p

async def handle(u):await u.asr.handleAudioMessage(u.conn,b'synthetic-controlled-pcm')

async def tail_and_new_round():
 u=await setup(timeout=1)
 try:
  p=await eos(u);old=guard.OutputLease(u.conn,'old');bind_input(u)
  # 支持的持久会话层仍须收到原一次have_voice，不能被新接缝跳过。
  u.conn.features['persistent_session']=True;u.conn._longmemory_session_idle=True
  await handle(u)
  assert u.conn.test_events==['vad','interrupt_return','prior_seam','asr_receive']
  assert u.conn.vad.calls==1 and not old.current() and not u.conn._longmemory_session_idle
  assert json.loads(await u.next())['state']=='interrupt' and u.consumer.queue==[]
  await handle(u)
  assert p.counts['interrupt_sent']==1 and u.conn.vad.calls==2
  u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
  await u.send.send_tts_message(u.conn,'start');assert json.loads(await u.next())['output_epoch']==2
  await u.send._do_send_audio(u.conn,b'late-old',{'sentence_id':'old','packet_count':0})
  for value in (b'fresh-one',b'fresh-two'):
   await u.send._do_send_audio(u.conn,value,{'sentence_id':'new','packet_count':0})
   assert await u.next()==value
  assert u.consumer.queue==[b'fresh-one',b'fresh-two'] and b'late-old' not in u.trace
  assert not p.turn.revoked and p.counts['interrupt_sent']==1
  return {'vad_once_per_packet':True,'interrupt_before_asr':True,'repeat_idempotent':True,'fresh_round_complete':True}
 finally:await u.cleanup()

async def gates():
 rows=[]
 for kind in ('idle_no_target','revoked','manual','no_aec','vad_false','active_speaking'):
  u=await setup(timeout=1)
  try:
   p=getattr(u.conn,wire.ATTRIBUTE)
   if kind!='idle_no_target':await eos(u)
   if kind=='revoked':
    await u.receive.handleAbortMessage(u.conn);await u.next()
   if kind=='active_speaking':
    u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
    await u.send.send_stt_message(u.conn,'synthetic new input')
    assert json.loads(await u.next())['type']=='stt';await u.next()
    assert u.conn.client_is_speaking and not p.turn.eos
   bind_input(u,kind!='vad_false')
   if kind=='manual':u.conn.client_listen_mode='manual'
   if kind=='no_aec':u.conn.client_aec=False
   before=p.counts['interrupt_sent'];await handle(u)
   expected=1 if kind=='active_speaking' else 0
   assert p.counts['interrupt_sent']-before==expected and u.conn.vad.calls==1
   if expected:await u.next()
   rows.append(kind)
  finally:await u.cleanup()
 return rows

async def wake_and_listen_reset():
 u=await setup(timeout=1)
 try:
  p=await eos(u);old=guard.OutputLease(u.conn,'old');bind_input(u)
  entered,release=asyncio.Event(),asyncio.Event();delays=[]
  async def sleep(seconds):delays.append(seconds);entered.set();await release.wait()
  u.receive.asyncio=NS(create_task=asyncio.create_task,sleep=sleep)
  u.conn.just_woken_up=True;await handle(u);await entered.wait()
  assert delays==[2] and u.conn.test_events==['vad'] and p.counts['interrupt_sent']==0
  release.set();await u.conn.vad_resume_task;assert u.conn.just_woken_up is False
  reset=load_method('core/connection.py','reset_audio_states',{'TAG':'test'},'ConnectionHandler')
  u.Connection.reset_audio_states=reset
  from collections import deque
  c=u.conn;c.client_audio_buffer=bytearray(b'xx');c.client_voice_window=deque([True],maxlen=5)
  c.asr_audio=[b'xx'];c.client_have_voice=c.client_voice_stop=c.last_is_voice=True
  c.vad_last_voice_time=123;c._vad_state=object();c._vad_context=object();rnn,context=c._vad_state,c._vad_context
  listen=load_method('core/handle/textHandler/listenMessageHandler.py','handle',
   {'Dict':dict,'Any':object,'TAG':'test'},'ListenTextMessageHandler')
  await listen(None,c,{'state':'start','mode':'realtime'})
  assert not c.asr_audio and not c.client_audio_buffer and not c.client_voice_window
  assert c._vad_state is rnn and c._vad_context is context and old.current()
  c.test_events.clear();await handle(u);await u.next()
  assert c.test_events==['vad','interrupt_return','prior_seam','asr_receive'] and not old.current()
  await listen(None,c,{'state':'start','mode':'realtime'});await handle(u)
  assert not old.current() and p.counts['interrupt_sent']==1
  return {'original_two_second_timer_requested':True,'no_asr_during_wake_drop':True,'listen_reset_no_lease_resurrection':True}
 finally:await u.cleanup()

async def target_replaced_before_seam():
 u=await setup(timeout=1)
 try:
  p=await eos(u);old=guard.OutputLease(u.conn,'old');bind_input(u)
  entered,release=asyncio.Event(),asyncio.Event();prior=u.receive.no_voice_close_connect
  async def delayed(c,have_voice):entered.set();await release.wait();return await prior(c,have_voice)
  u.receive.no_voice_close_connect=delayed
  task=asyncio.create_task(handle(u));await entered.wait()
  u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
  await u.send.send_tts_message(u.conn,'start')
  assert json.loads(await u.next())['output_epoch']==2  # 旧EOS正常切新轮，不额外生成interrupt。
  await u.send._do_send_audio(u.conn,b'new-pending',{'sentence_id':'new','packet_count':0});await u.next()
  fresh=p.turn;release.set();await task
  assert p.turn is fresh and not fresh.revoked and p.counts['interrupt_sent']==0
  assert u.consumer.queue==[b'new-pending'] and not old.current()
  return {'captured_old_target_cannot_revoke_new_epoch':True}
 finally:await u.cleanup()

async def cancel_waiting_abort():
 u=await setup(timeout=1)
 try:
  p=await eos(u);bind_input(u);await p.gate.acquire()
  task=asyncio.create_task(handle(u))
  for _ in range(100):
   if p.turn.revoked:break
   await asyncio.sleep(.001)
  assert p.turn.revoked;task.cancel()
  try:await task
  except asyncio.CancelledError:pass
  else:raise AssertionError('caller cancellation swallowed')
  p.gate.release();assert guard._EOS_INPUT.get() is None
  u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
  await u.send.send_tts_message(u.conn,'start')
  assert json.loads(await u.next())['state']=='interrupt';assert json.loads(await u.next())['output_epoch']==2
  assert not p.turn.revoked and p.counts['interrupt_sent']==1
  return {'cancel_preserved_context_reset_and_new_epoch':True}
 finally:await u.cleanup()

async def mode_changed_before_seam():
 for kind in ('manual','no_aec'):
  u=await setup(timeout=1)
  try:
   p=await eos(u);bind_input(u)
   entered,release=asyncio.Event(),asyncio.Event();prior=u.receive.no_voice_close_connect
   async def delayed(c,have_voice):entered.set();await release.wait();return await prior(c,have_voice)
   u.receive.no_voice_close_connect=delayed
   task=asyncio.create_task(handle(u));await entered.wait()
   if kind=='manual':u.conn.client_listen_mode='manual'
   else:u.conn.client_aec=False
   release.set();await task
   assert not p.turn.revoked and p.counts['interrupt_sent']==0
  finally:await u.cleanup()
 return {'manual_and_no_aec_changes_preserved':True}

async def main():
 report={'kind':'synthetic_vad_control_flow_not_acoustic_or_device_ack','tail':await tail_and_new_round(),
  'gates':await gates(),'wake_reset':await wake_and_listen_reset(),
  'replacement':await target_replaced_before_seam(),'cancel':await cancel_waiting_abort(),
  'mode_change':await mode_changed_before_seam()}
 assert 'torch' not in sys.modules
 print(json.dumps(report))
asyncio.run(main())
'''


@pytest.mark.skipif(not WIRE_CASES.PYTHON.is_file(), reason="owner-installed websockets runtime unavailable")
def test_native_vad_eos_tail_real_wrappers_and_loopback(tmp_path, record_testsuite_property):
    driver = tmp_path / "eos_vad_driver.py"
    driver.write_text(PREFIX + CASES, encoding="utf-8")
    result = subprocess.run([str(WIRE_CASES.PYTHON), "-B", "-X", "utf8", str(driver)],
        input=json.dumps({"root": str(ROOT), "voice": str(WIRE_CASES.VOICE)}).encode(),
        capture_output=True, cwd=ROOT, timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-6000:]
    report = json.loads(result.stdout)
    record_testsuite_property("synthetic_eos_control_report", json.dumps(report, sort_keys=True))
    (tmp_path / "eos-vad-control.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["tail"]["interrupt_before_asr"]
    assert report["replacement"]["captured_old_target_cannot_revoke_new_epoch"]
    assert report["cancel"]["cancel_preserved_context_reset_and_new_epoch"]
