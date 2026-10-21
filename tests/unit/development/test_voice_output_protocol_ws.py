"""真实随机环回WebSocket线序；固定SDK AST+合成连接/消费者合同预言机，无模型或设备。"""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
VOICE = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
PYTHON = VOICE / ".venv/Scripts/python.exe"

DRIVER = r'''
import ast,asyncio,json,subprocess,sys,traceback,time
from pathlib import Path
from types import SimpleNamespace as NS
cfg=json.load(sys.stdin);root=Path(cfg['root']);voice=Path(cfg['voice'])
sys.path.insert(0,str(root/'scripts/development/xiaozhi'))
sys.path.insert(0,str(root/'tests/fixtures'))
import websockets
from voice_interruption_upstream import build,UPSTREAM,PIN
import voice_interruption as guard
import voice_output_protocol as wire

def load_method(path,name,namespace,cls=None):
 src=subprocess.check_output(['git','-C',str(UPSTREAM),'show',PIN+':main/xiaozhi-server/'+path],text=True,encoding='utf-8')
 tree=ast.parse(src)
 nodes=tree.body if cls is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls).body
 node=next(n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
 exec(compile(ast.Module(body=[node],type_ignores=[]),'pinned:'+name,'exec'),namespace)
 return namespace[name]

class Consumer:
 # 合同预言机，不是对尚未实施的AH固件行为的证明。
 def __init__(self,advertised):self.advertised=advertised;self.v1=False;self.epoch=0;self.open=False;self.queue=[];self.resets=0
 def receive(self,value):
  if isinstance(value,bytes):
   if self.open:self.queue.append(value)
   return
  msg=json.loads(value)
  if msg.get('type')=='hello':self.v1=self.advertised is True and msg.get('features',{}).get(wire.CAPABILITY) is True;return
  if msg.get('type')!='tts':return
  state=msg['state'];epoch=msg.get('output_epoch')
  if not self.v1:
   if state=='start':self.open=True
   if state=='stop':self.open=False # legacy不清已收队列。
   return
  if type(epoch) is not int or not 1<=epoch<=wire.MAX_EPOCH:return
  if state=='start' and epoch>self.epoch:self.epoch=epoch;self.open=True;self.queue=[];self.resets+=1
  elif epoch==self.epoch and state=='interrupt':self.open=False;self.queue=[]
  elif epoch==self.epoch and state=='stop':self.open=False

async def setup(cap=True,mode='pipeline',mqtt=False,timeout=.3,local_cosy=True,bridge=False,observed=False):
 u=build();c=u.conn
 c.config={'xiaozhi':{'type':'hello','transport':'websocket','audio_params':{'sample_rate':16000},
    'features':{wire.CAPABILITY:True}},'selected_module':{'TTS':'CustomTTS'},
    'TTS':{'CustomTTS':{'url':'http://127.0.0.1:18770/v1/audio/speech'}}}
 c.voice_mode=mode
 if not local_cosy:
  c.config['selected_module']['TTS']='EdgeTTS';c.tts._longmemory_cosy_streaming_installed=False
 if bridge:c._doubao_bridge=NS()
 c.client_aec=False
 c._check_timeout=c._check_aec_cache_expiry=lambda:asyncio.Event().wait()
 async def init():pass
 c._background_initialize=init
 async def save(ws):
  for task in (c.timeout_task,c._aec_cache_cleanup_task):task.cancel()
  await asyncio.gather(c.timeout_task,c._aec_cache_cleanup_task,return_exceptions=True)
 c._save_and_close=save
 hello=load_method('core/handle/helloHandle.py','handleHelloMessage',{'json':json,'asyncio':asyncio,'TAG':'test'})
 async def route(message):
  if isinstance(message,str) and json.loads(message).get('type')=='hello':await hello(c,json.loads(message))
 c._route_message=route
 namespace={'websockets':websockets,'asyncio':asyncio,'time':__import__('time'),'TAG':'test',
  'AuthenticationError':type('SyntheticAuthError',(Exception,),{}),'traceback':traceback}
 u.Connection.handle_connection=load_method('core/connection.py','handle_connection',namespace,'ConnectionHandler')
 u.hello_alias=NS(sendAudioMessage=u.send.sendAudioMessage,send_tts_message=u.send.send_tts_message)
 u.listen_alias=NS(send_tts_message=u.send.send_tts_message)
 if observed:
  import voice_latency,voice_waiting
  u.ttsbase.sendAudioMessage=voice_latency.observed_audio_sender(u.ttsbase.sendAudioMessage)
  u.send._do_send_audio=voice_latency.observed_cosy_packet_sender(u.send._do_send_audio)
  voice_waiting.install_waiting_sender(u.send)
 guard.install_voice_interruption(u.Connection,u.receive,u.asr,u.send,tts_base_module=u.ttsbase)
 wire.install_tts_interrupt_protocol(u.Connection,u.send,hello_module=u.hello_alias,
  listen_module=u.listen_alias,upstream_root=voice,send_timeout=timeout)
 server=await websockets.serve(c.handle_connection,'127.0.0.1',0,close_timeout=.1)
 port=server.sockets[0].getsockname()[1]
 client=await websockets.connect('ws://127.0.0.1:'+str(port)+('/?from=mqtt_gateway' if mqtt else '/'),close_timeout=.1)
 await client.send(json.dumps({'type':'hello','features':{wire.CAPABILITY:cap},'audio_params':{'sample_rate':16000}}))
 greeting=await asyncio.wait_for(client.recv(),2)
 consumer=Consumer(cap);consumer.receive(greeting)
 inbox=asyncio.Queue();trace=[greeting];arrivals=[]
 async def receive():
  try:
   async for value in client:
    trace.append(value);arrivals.append((time.perf_counter(),value));consumer.receive(value);await inbox.put(value)
  except websockets.ConnectionClosed:pass
 receiver=asyncio.create_task(receive())
 async def next():return await asyncio.wait_for(inbox.get(),2)
 async def cleanup():
  await client.close();await receiver;server.close();await server.wait_closed()
 u.__dict__.update(client=client,server=server,consumer=consumer,inbox=inbox,trace=trace,arrivals=arrivals,next=next,cleanup=cleanup)
 return u

async def case_handshake():
 rows=[]
 for cap,mode,mqtt,local,bridge in ((False,'pipeline',False,True,False),(True,'pipeline',False,True,False),
        ('true','pipeline',False,True,False),(True,'doubao_realtime',False,True,False),
        (True,'pipeline',True,True,False),(True,'pipeline',False,False,False),(True,'pipeline',False,True,True)):
  u=await setup(cap,mode,mqtt,local_cosy=local,bridge=bridge)
  try:
   expected=cap is True and mode=='pipeline' and not mqtt and local and not bridge
   assert u.consumer.v1==expected
   assert wire.protocol_snapshot(u.conn)['negotiated']==expected
   await u.send.send_tts_message(u.conn,'start');start=json.loads(await u.next())
   assert ('output_epoch' in start)==expected
   await u.send._do_send_audio(u.conn,b'audio',{'sentence_id':'old','packet_count':0})
   audio=await u.next();assert isinstance(audio,bytes) and audio.endswith(b'audio')
   await u.receive.handleAbortMessage(u.conn)
   stop=json.loads(await u.next())
   assert stop['state']==('interrupt' if expected else 'stop')
   assert u.consumer.queue==([] if expected else [audio])
   assert u.conn.config['xiaozhi']['features'][wire.CAPABILITY] is True
   rows.append({'v1':expected,'mode':mode,'mqtt':mqtt})
  finally:await u.cleanup()
 return rows

async def case_order():
 u=await setup(timeout=1)
 try:
  await u.send.send_tts_message(u.conn,'start');assert json.loads(await u.next())['output_epoch']==1
  p=getattr(u.conn,wire.ATTRIBUTE);raw_send=p.raw.send
  entered,release=asyncio.Event(),asyncio.Event()
  async def blocked(value):
   if value==b'old-inflight':entered.set();await release.wait()
   return await raw_send(value)
  p.raw.send=blocked
  old=asyncio.create_task(u.send._do_send_audio(u.conn,b'old-inflight',{'sentence_id':'old','packet_count':0}))
  await entered.wait()
  queued=asyncio.create_task(u.send._do_send_audio(u.conn,b'old-queued',{'sentence_id':'old','packet_count':0}))
  cancelled=asyncio.create_task(u.send._do_send_audio(u.conn,b'cancelled-waiter',{'sentence_id':'old','packet_count':0}))
  await asyncio.sleep(0);cancelled.cancel();await asyncio.gather(cancelled,return_exceptions=True)
  guard.state_for(u.conn).active=True
  abort=asyncio.create_task(u.asr.startToChat(u.conn,'synthetic input'))
  await asyncio.sleep(.02)
  release.set();await asyncio.gather(old,queued,abort)
  assert await u.next()==b'old-inflight'
  assert json.loads(await u.next())['state']=='interrupt'
  assert json.loads(await u.next())['type']=='stt'
  assert json.loads(await u.next())['output_epoch']==2
  assert u.consumer.queue==[]
  assert u.conn.client_abort is False and u.conn.sentence_id=='old'
  u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
  await u.send._do_send_audio(u.conn,b'new',{'sentence_id':'new','packet_count':0})
  assert await u.next()==b'new'
  await u.listen_alias.send_tts_message(u.conn,'stop')
  eos=json.loads(await u.next());assert eos['state']=='stop' and eos['output_epoch']==2
  assert u.consumer.queue==[b'new'] # normalEOS不截尾。
  assert b'old-queued' not in u.trace
  assert b'cancelled-waiter' not in u.trace
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_timeout():
 u=await setup(timeout=.08)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  p=getattr(u.conn,wire.ATTRIBUTE);original=p.raw.send;entered=asyncio.Event()
  async def blocked(value):entered.set();await asyncio.Event().wait();await original(value)
  p.raw.send=blocked
  before=asyncio.get_running_loop().time()
  with_error=False
  try:await u.send._do_send_audio(u.conn,b'never-written',{'sentence_id':'old','packet_count':0})
  except wire.OutputUnavailable:with_error=True
  assert with_error
  assert asyncio.get_running_loop().time()-before<1.2
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert b'never-written' not in u.trace
  value=wire.protocol_snapshot(u.conn)
  assert value['state']=='closed' and not value['device_playback_acknowledged']
  assert value['active_writes']==0
  return value
 finally:await u.cleanup()

async def case_alias_eos():
 u=await setup(timeout=1)
 try:
  await u.hello_alias.send_tts_message(u.conn,'start');await u.next()
  entered,release=asyncio.Event(),asyncio.Event()
  # 原生stop仍在等音频；新start可先于新UUID创建，旧stop必须在破坏新controller之前退出。
  original_wait=u.send._wait_for_audio_completion
  async def blocked_wait(conn):entered.set();await release.wait();await original_wait(conn)
  u.send._wait_for_audio_completion=blocked_wait
  stopped=[];u.conn.audio_rate_controller=NS(stop_sending=lambda:stopped.append(True),reset=lambda:None)
  old=asyncio.create_task(u.listen_alias.send_tts_message(u.conn,'stop'))
  await entered.wait()
  await u.hello_alias.send_tts_message(u.conn,'start')
  assert json.loads(await u.next())['state']=='interrupt'
  assert json.loads(await u.next())['output_epoch']==2
  release.set();await old
  assert stopped==[]
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_late_input_repeat_hello():
 u=await setup(timeout=1)
 try:
  entered,release=asyncio.Event(),asyncio.Event()
  async def intent(conn,text):
   if text=='first':entered.set();await release.wait()
   return False
  u.receive.handle_user_intent=intent
  old=asyncio.create_task(u.asr.startToChat(u.conn,'first'))
  await entered.wait()
  await u.asr.startToChat(u.conn,'second')
  assert json.loads(await u.next())['type']=='stt'
  start=json.loads(await u.next());assert start['output_epoch']==1
  release.set();await old
  assert u.calls.count('submit')==1
  await u.client.send(json.dumps({'type':'hello','features':{wire.CAPABILITY:False}}))
  repeat=json.loads(await u.next());assert repeat['features'][wire.CAPABILITY] is True
  assert getattr(u.conn,wire.ATTRIBUTE).next_epoch==1
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_paths():
 from voice_waiting import WaitingTurn,WaitingPacket,AnswerPacket
 u=await setup(timeout=1)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  waiting=u.conn._longmemory_waiting=WaitingTurn(u.conn,'model',delay=0,packets=(b'cue',))
  await u.ttsbase.sendAudioMessage(u.conn,'middle',[WaitingPacket(b'cue',waiting)],None,'old')
  assert await u.next()==b'cue'
  await u.hello_alias.sendAudioMessage(u.conn,'first',[AnswerPacket(b'preset',waiting)],'synthetic subtitle','old')
  # 固定原生FIRST在已有controller时把字幕排队，但预缓冲音频可能先直发。
  pair=[await u.next(),await u.next()]
  assert b'preset' in pair
  subtitle=json.loads(next(value for value in pair if isinstance(value,str)))
  assert subtitle['state']=='sentence_start' and subtitle['output_epoch']==1
  # 停止提示音由原生EOS路径产生，仍在同一个输出epoch和最终发送门。
  async def notify(*a,**kw):return [b'notify']
  u.send.audio_to_data=notify;u.conn.config['enable_stop_tts_notify']=True
  await u.send.send_tts_message(u.conn,'stop')
  assert await u.next()==b'notify'
  eos=json.loads(await u.next());assert eos['output_epoch']==1 and eos['state']=='stop'
  assert u.consumer.queue==[b'cue',b'preset',b'notify']
  try:await u.conn.websocket.send(b'unowned')
  except wire.StaleOutput:pass
  else:raise AssertionError('unowned v1 binary accepted')
  # 未确认的legacy会话不能在重复hello时升级。
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_legacy_repeat_and_exhaustion():
 u=await setup(False)
 try:
  await u.client.send(json.dumps({'type':'hello','features':{wire.CAPABILITY:True}}))
  assert wire.CAPABILITY not in json.loads(await u.next()).get('features',{})
  assert not wire.protocol_snapshot(u.conn)['negotiated']
 finally:await u.cleanup()
 u=await setup()
 try:
  p=getattr(u.conn,wire.ATTRIBUTE);p.next_epoch=wire.MAX_EPOCH
  try:await u.send.send_tts_message(u.conn,'start')
  except wire.OutputUnavailable:pass
  else:raise AssertionError('epoch wrapped')
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert wire.protocol_snapshot(u.conn)['reason']=='epoch_exhausted'
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_close_inflight():
 u=await setup(timeout=1)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  p=getattr(u.conn,wire.ATTRIBUTE);original=p.raw.send;entered=asyncio.Event()
  async def blocked(value):entered.set();await asyncio.Event().wait();await original(value)
  p.raw.send=blocked
  send=asyncio.create_task(u.send._do_send_audio(u.conn,b'closed-old',{'sentence_id':'old','packet_count':0}))
  await entered.wait();await asyncio.wait_for(p.close(),1)
  await asyncio.gather(send,return_exceptions=True)
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert b'closed-old' not in u.trace
  assert wire.protocol_snapshot(u.conn)['active_writes']==0
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_real_opus_pacing():
 import os,math,struct
 sys.path.append(str(voice))
 dllpath=voice/'native/libopus-1.6.1/Library/bin'
 os.environ['PATH']=str(dllpath)+os.pathsep+os.environ.get('PATH','')
 dll=os.add_dll_directory(str(dllpath))
 from core.utils.opus_encoder_utils import OpusEncoderUtils
 from opuslib_next import Decoder
 encoder=OpusEncoderUtils(16000,1,60)
 def tone(frequency,frames):
  packets=[];pcm=struct.pack('<'+'h'*(960*frames),
   *(int(10000*math.sin(2*math.pi*frequency*i/16000)) for i in range(960*frames)))
  encoder.encode_pcm_to_opus_stream(pcm,end_of_stream=True,callback=packets.append)
  return packets
 u=await setup(timeout=2)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  old=tone(440,20)
  await u.ttsbase.sendAudioMessage(u.conn,'middle',old,None,'old')
  first=await u.next();pcm=Decoder(16000,1).decode(first,960)
  assert sum(abs(v)>=200 for v in struct.unpack('<960h',pcm))>=80
  await u.asr.startToChat(u.conn,'synthetic voiced handoff')
  seen=[]
  while True:
   row=await u.next();seen.append(row)
   if isinstance(row,str) and json.loads(row).get('state')=='start':break
  interrupt=next(i for i,row in enumerate(seen) if isinstance(row,str) and json.loads(row).get('state')=='interrupt')
  assert not any(isinstance(row,bytes) for row in seen[interrupt+1:])
  u.conn.sentence_id=u.conn.tts.current_sentence_id='new'
  encoder.reset_state();new=tone(880,20)
  await u.ttsbase.sendAudioMessage(u.conn,'middle',new,None,'new')
  await u.send.send_tts_message(u.conn,'stop')
  received=[]
  while True:
   row=await u.next()
   if isinstance(row,str) and json.loads(row).get('state')=='stop':break
   if isinstance(row,bytes):received.append(row)
  assert received==new and len(received)==20
  decoder=Decoder(16000,1)
  for row in received:
   pcm=decoder.decode(row,960)
   assert sum(abs(v)>=200 for v in struct.unpack('<960h',pcm))>=80
  times=[at for at,row in u.arrivals if isinstance(row,bytes) and row in new]
  span=(times[-1]-times[0])*1000
  assert span>=750 # 原生前5帧直发+队列首帧立即，其余按60ms调度；不能全段突发。
  return {'new_frames':20,'new_frame_arrival_span_ms':round(span,3),'old_after_interrupt':0,
          'first_old_decoded_frame_energy_qualified':True,'physical_playback_verified':False}
 finally:await u.cleanup();encoder.close();dll.close()

async def case_cancelled_inflight():
 u=await setup(timeout=1)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  p=getattr(u.conn,wire.ATTRIBUTE);raw=p.raw.send;entered,release=asyncio.Event(),asyncio.Event()
  async def blocked(value):
   if value==b'cancelled-inflight':entered.set();await release.wait()
   return await raw(value)
  p.raw.send=blocked
  old=asyncio.create_task(u.send._do_send_audio(u.conn,b'cancelled-inflight',{'sentence_id':'old','packet_count':0}))
  await entered.wait();old.cancel();await asyncio.sleep(0)
  guard.state_for(u.conn).active=True
  abort=asyncio.create_task(u.asr.startToChat(u.conn,'synthetic input'))
  await asyncio.sleep(.01);release.set()
  await asyncio.gather(old,return_exceptions=True);await abort
  assert await u.next()==b'cancelled-inflight'
  assert json.loads(await u.next())['state']=='interrupt'
  assert json.loads(await u.next())['type']=='stt'
  assert json.loads(await u.next())['output_epoch']==2
  assert wire.protocol_snapshot(u.conn)['active_writes']==0
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_gate_timeout_and_coverage():
 u=await setup(timeout=1)
 try:
  await u.send.send_tts_message(u.conn,'start');await u.next()
  p=getattr(u.conn,wire.ATTRIBUTE);entered=asyncio.Event()
  async def blocked(value):entered.set();await asyncio.Event().wait()
  p.raw.send=blocked
  old=asyncio.create_task(u.send._do_send_audio(u.conn,b'gate-old',{'sentence_id':'old','packet_count':0}))
  await entered.wait();p.send_timeout=.05
  try:await u.send.send_tts_message(u.conn,'start')
  except wire.OutputUnavailable:pass
  else:raise AssertionError('gate timeout missing')
  await asyncio.gather(old,return_exceptions=True)
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert wire.protocol_snapshot(u.conn)['reason']=='gate_timeout'
  assert wire.protocol_snapshot(u.conn)['active_writes']==0
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_revoke_during_implicit_start():
 u=await setup(timeout=1)
 try:
  p=getattr(u.conn,wire.ATTRIBUTE);raw=p.raw.send;entered,release=asyncio.Event(),asyncio.Event()
  async def blocked(value):
   if isinstance(value,str) and json.loads(value).get('state')=='start':entered.set();await release.wait()
   return await raw(value)
  p.raw.send=blocked
  old=asyncio.create_task(u.send._do_send_audio(u.conn,b'implicit-old',{'sentence_id':'old','packet_count':0}))
  await entered.wait()
  abort=asyncio.create_task(u.receive.handleAbortMessage(u.conn))
  await asyncio.sleep(.01);release.set();await asyncio.gather(old,abort)
  assert json.loads(await u.next())['state']=='start'
  assert json.loads(await u.next())['state']=='interrupt'
  assert b'implicit-old' not in u.trace
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_coverage_changed():
 u=await setup()
 try:
  previous=u.hello_alias.send_tts_message
  async def changed(*a,**kw):return await previous(*a,**kw)
  u.hello_alias.send_tts_message=changed
  try:await u.send.send_tts_message(u.conn,'start')
  except wire.OutputUnavailable:pass
  else:raise AssertionError('coverage changed without close')
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert wire.protocol_snapshot(u.conn)['reason']=='mode_changed'
  return wire.protocol_snapshot(u.conn)
 finally:await u.cleanup()

async def case_eos_tail_interrupt():
 rows=[]
 for origin in ('formal_asr','explicit_abort','control_stop'):
  u=await setup(timeout=1)
  try:
   await u.send.send_tts_message(u.conn,'start');await u.next()
   await u.send._do_send_audio(u.conn,b'pending-tail',{'sentence_id':'old','packet_count':0})
   assert await u.next()==b'pending-tail'
   await u.send.send_tts_message(u.conn,'stop')
   eos=json.loads(await u.next());assert eos['state']=='stop' and eos['output_epoch']==1
   assert u.consumer.queue==[b'pending-tail']  # 普通EOS仍保留完整尾音。
   assert not guard.state_for(u.conn).active and not u.conn.client_is_speaking
   if origin=='formal_asr':await u.asr.startToChat(u.conn,'synthetic next input')
   elif origin=='explicit_abort':await u.receive.handleAbortMessage(u.conn)
   else:
    from device_control import DeviceControl
    control=DeviceControl('synthetic',response_aborter=u.receive.handleAbortMessage)
    control._connection=lambda:u.conn
    u.conn.loop=asyncio.get_running_loop()
    result=await control.stop_speech()
    assert result['state']=='stop_sent' and result['device_acknowledgement']=='unavailable'
    assert (await control.stop_speech())['state']=='already_idle'
   interrupt=json.loads(await u.next())
   assert interrupt['state']=='interrupt' and interrupt['output_epoch']==1
   assert u.consumer.queue==[]
   if origin=='formal_asr':
    assert json.loads(await u.next())['type']=='stt'
    assert json.loads(await u.next())['output_epoch']==2
   assert wire.protocol_snapshot(u.conn)['counts']['interrupt_sent']==1
   rows.append({'origin':origin,'eos_preserved_tail':True,'interrupt_epoch':1})
  finally:await u.cleanup()
 return rows

async def case_observed_answer_and_waiting_gate(cap=True):
 import voice_latency,voice_waiting
 u=await setup(cap,timeout=1,observed=True)
 try:
  c=u.conn;p=getattr(c,wire.ATTRIBUTE)
  tracker=c._longmemory_voice_latency=voice_latency.VoiceLatencyTracker(c)
  tracker.begin();c.sentence_id=c.tts.current_sentence_id='observed';tracker.bind_sentence()
  state=c._longmemory_waiting=voice_waiting.WaitingTurn(c,'model',delay=0,packets=(b'cue',))
  await u.send.send_tts_message(c,'start');await u.next()
  raw=p.raw.send;entered,release=asyncio.Event(),asyncio.Event()
  blocker_text=json.dumps({'type':'synthetic_blocker'})
  async def blocked(value):
   if value==blocker_text:entered.set();await release.wait()
   return await raw(value)
  p.raw.send=blocked
  blocker=asyncio.create_task(c.websocket.send(blocker_text));await entered.wait()
  cue=asyncio.create_task(u.ttsbase.sendAudioMessage(c,'middle',voice_waiting.WaitingPacket(b'late-cue',state),None,c.sentence_id))
  for _ in range(20):
   if state.budget.inflight is not None:break
   await asyncio.sleep(0)
  assert state.budget.inflight is not None
  voice_waiting.mark_answer_ready(c)
  answer=asyncio.create_task(u.ttsbase.sendAudioMessage(c,'middle',voice_waiting.AnswerPacket(b'observed-answer',state),None,c.sentence_id))
  release.set();await asyncio.gather(blocker,cue,answer)
  assert await u.next()==blocker_text
  assert await u.next()==b'observed-answer'
  assert b'late-cue' not in u.trace
  assert state.budget.last_sent_at is None
  assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is not None
  assert state.first_feedback_ms is None and state.first_answer_ms is not None
  return {'negotiated':cap,'answer_timing_present':True,'waiting_consumed_cooldown':False,'physical_playback_verified':False}
 finally:await u.cleanup()

async def case_legacy_packet_gate_and_unowned_compatibility():
 import voice_latency,voice_waiting
 rows=[]
 for reason in ('revoked_lease','callback_error'):
  u=await setup(False,observed=True,timeout=1)
  try:
   c=u.conn;p=getattr(c,wire.ATTRIBUTE)
   tracker=c._longmemory_voice_latency=voice_latency.VoiceLatencyTracker(c)
   tracker.begin();c.sentence_id=c.tts.current_sentence_id='legacy-gate';tracker.bind_sentence()
   state=c._longmemory_waiting=voice_waiting.WaitingTurn(c,'model',delay=0,packets=(b'cue',))
   await u.send.send_tts_message(c,'start');await u.next()
   cls=voice_waiting.AnswerPacket if reason=='revoked_lease' else voice_waiting.WaitingPacket
   packet=cls(b'legacy-must-drop',state)
   failed=[False]
   original_cancelled=packet._longmemory_cosy_cancelled
   def cancelled():
    if failed[0]:raise RuntimeError('synthetic_cancel_check_error')
    return original_cancelled()
   packet._longmemory_cosy_cancelled=cancelled
   entered=asyncio.Event();send=c.websocket.send
   async def observed(value):
    if value==b'legacy-must-drop':entered.set()
    return await send(value)
   c.websocket.send=observed
   await p.gate.acquire()
   task=asyncio.create_task(u.ttsbase.sendAudioMessage(c,'middle',packet,None,c.sentence_id))
   await asyncio.wait_for(entered.wait(),1)
   if reason=='revoked_lease':guard.state_for(c).revoke('asr_handoff_revoked')
   else:failed[0]=True
   assert c.client_abort is False  # 不能借可复位布尔通过这个负例。
   p.gate.release();await task
   assert packet._longmemory_send_receipt.sent_at is None
   assert state.budget.last_sent_at is None
   assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is None
   # 无包归属的legacy控制/心跳/二进制保持原样，不补epoch、不强制租约。
   for value in (json.dumps({'type':'session','state':'heartbeat'}),
                 json.dumps({'type':'tts','state':'stop','session_id':c.session_id}),b'legacy-unowned'):
    await c.websocket.send(value);assert await u.next()==value
   assert b'legacy-must-drop' not in u.trace
   assert wire.protocol_snapshot(c)['state']=='legacy'
   rows.append({'reason':reason,'dropped':True,'unowned_legacy_compatible':True})
  finally:await u.cleanup()
 return rows

async def case_observed_actual_send_receipts():
 import voice_latency,voice_waiting
 results=[]
 for cap in (False,True):
  u=await setup(cap,observed=True,timeout=1)
  try:
   c=u.conn;tracker=c._longmemory_voice_latency=voice_latency.VoiceLatencyTracker(c)
   tracker.begin();c.sentence_id=c.tts.current_sentence_id='receipt';tracker.bind_sentence()
   state=c._longmemory_waiting=voice_waiting.WaitingTurn(c,'model',delay=0,packets=(b'cue',))
   await u.send.send_tts_message(c,'start');await u.next()
   cue=voice_waiting.WaitingPacket(b'receipt-cue',state)
   await u.ttsbase.sendAudioMessage(c,'middle',cue,None,c.sentence_id)
   assert await u.next()==b'receipt-cue'
   assert cue._longmemory_send_receipt.sent_at is not None and state.budget.last_sent_at is not None
   assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is None
   voice_waiting.mark_answer_ready(c)
   answer=voice_waiting.AnswerPacket(b'receipt-answer',state)
   await u.ttsbase.sendAudioMessage(c,'middle',answer,None,c.sentence_id)
   assert await u.next()==b'receipt-answer'
   assert answer._longmemory_send_receipt.sent_at is not None
   assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is not None
   # marker仅为进程内属性；线上接收的字节与原缓存/答案完全相同。
   results.append({'negotiated':cap,'answer_marked':True,'cue_separate':True})
  finally:await u.cleanup()
 return results

async def case_observed_receipt_cancel_and_failure():
 import voice_latency,voice_waiting
 u=await setup(observed=True,timeout=1)
 try:
  c=u.conn;p=getattr(c,wire.ATTRIBUTE)
  tracker=c._longmemory_voice_latency=voice_latency.VoiceLatencyTracker(c)
  tracker.begin();c.sentence_id=c.tts.current_sentence_id='cancel-return';tracker.bind_sentence()
  state=c._longmemory_waiting=voice_waiting.WaitingTurn(c,'model',delay=0,packets=(b'cue',))
  await u.send.send_tts_message(c,'start');await u.next()
  raw=p.raw.send
  async def sent_then_cancel(value):
   result=await raw(value)
   if value==b'sent-before-cancel':state.cancel()
   return result
  p.raw.send=sent_then_cancel
  cue=voice_waiting.WaitingPacket(b'sent-before-cancel',state)
  await u.ttsbase.sendAudioMessage(c,'middle',cue,None,c.sentence_id)
  assert await u.next()==b'sent-before-cancel'
  assert state.closed and cue._longmemory_send_receipt.sent_at is not None
  assert state.budget.last_sent_at is not None and state.first_feedback_ms is not None
  assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is None
 finally:await u.cleanup()
 u=await setup(observed=True,timeout=1)
 try:
  c=u.conn;p=getattr(c,wire.ATTRIBUTE)
  tracker=c._longmemory_voice_latency=voice_latency.VoiceLatencyTracker(c)
  tracker.begin();c.sentence_id=c.tts.current_sentence_id='failed';tracker.bind_sentence()
  state=c._longmemory_waiting=voice_waiting.WaitingTurn(c,'model',delay=0,packets=(b'cue',))
  await u.send.send_tts_message(c,'start');await u.next()
  async def fail(value):raise RuntimeError('synthetic_transport_failure')
  p.raw.send=fail
  answer=voice_waiting.AnswerPacket(b'never-sent',state)
  try:await u.ttsbase.sendAudioMessage(c,'middle',answer,None,c.sentence_id)
  except RuntimeError:pass
  else:raise AssertionError('transport failure hidden')
  await asyncio.wait_for(u.client.wait_closed(),1)
  assert answer._longmemory_send_receipt.sent_at is None
  assert tracker.snapshot()['timings_ms']['first_audio_sent_ms'] is None
  assert b'never-sent' not in u.trace
  return {'sent_then_cancel_consumed':True,'failed_answer_not_marked':True}
 finally:await u.cleanup()

async def main():
 result={'handshake':await case_handshake(),'ordered':await case_order(),
         'timeout':await case_timeout(),'alias_eos':await case_alias_eos(),
         'late_input':await case_late_input_repeat_hello(),'paths':await case_paths(),
         'exhausted':await case_legacy_repeat_and_exhaustion(),'close':await case_close_inflight(),
         'opus_pacing':await case_real_opus_pacing(),'cancelled_inflight':await case_cancelled_inflight(),
         'gate_timeout_coverage':await case_gate_timeout_and_coverage(),
         'coverage_changed':await case_coverage_changed(),
         'implicit_start':await case_revoke_during_implicit_start(),
         'eos_tail':await case_eos_tail_interrupt(),
         'observed_gate':await case_observed_answer_and_waiting_gate(),
         'legacy_observed_gate':await case_observed_answer_and_waiting_gate(False),
         'legacy_gate_compatibility':await case_legacy_packet_gate_and_unowned_compatibility(),
         'send_receipts':await case_observed_actual_send_receipts(),
         'receipt_cancel_failure':await case_observed_receipt_cancel_and_failure()}
 assert 'torch' not in sys.modules
 print(json.dumps(result))
asyncio.run(main())
'''


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed websockets runtime unavailable")
def test_bilateral_handshake_true_wire_order_eos_alias_and_bounded_close():
    result = subprocess.run([str(PYTHON), "-B", "-X", "utf8", "-c", DRIVER],
        input=json.dumps({"root": str(ROOT), "voice": str(VOICE)}).encode(),
        capture_output=True, cwd=ROOT, timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-6000:]
    report = json.loads(result.stdout)
    assert report["ordered"]["counts"]["interrupt_sent"] == 1
    assert report["ordered"]["counts"]["eos_sent"] == 1
    assert report["timeout"]["reason"] == "send_timeout"
    assert report["alias_eos"]["counts"]["eos_sent"] == 0
    print(json.dumps({"opus_pacing": report["opus_pacing"],
                      "send_timeout": report["timeout"]["reason"],
                      "gate_timeout": report["gate_timeout_coverage"]["reason"],
                      "coverage_changed": report["coverage_changed"]["reason"]}))
