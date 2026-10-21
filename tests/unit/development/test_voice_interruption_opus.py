"""随机环回HTTP→真实FIR/Opus→固定上游调度；在解码有声后执行正式识别交接。"""

import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace as NS

import pytest

from test_ad_cosy_http_opus import VOICE, PYTHON, _wave
from test_cosyvoice_service import service

ROOT = Path(__file__).resolve().parents[3]
DRIVER = r'''
import asyncio,json,os,queue,struct,sys,time
from pathlib import Path
from types import SimpleNamespace as NS
cfg=json.load(sys.stdin)
voice=Path(cfg['voice']);sys.path.insert(0,str(voice))
dllpath=voice/'native/libopus-1.6.1/Library/bin'
os.environ['PATH']=str(dllpath)+os.pathsep+os.environ.get('PATH','')
dll=os.add_dll_directory(str(dllpath))
from core.utils.opus_encoder_utils import OpusEncoderUtils
from opuslib_next import Decoder
root=Path(cfg['root']);sys.path.insert(0,str(root/'scripts/development/xiaozhi'))
sys.path.insert(0,str(root/'tests/fixtures'))
from voice_interruption_upstream import build
import voice_interruption as guard
import cosyvoice_streaming as client
client.STREAM_URL=cfg['url'];client.default_voice_active=lambda:False
u=build();conn=u.conn;tts=conn.tts
conn.sample_rate=cfg['rate'];conn._longmemory_cosy_reply_cache=False
conn._longmemory_cosy_delivery_mode=cfg['mode']
reports=[];wire=[];energy=[];produced=[]
conn._longmemory_voice_latency=NS(record_continuity=lambda value,**kw:reports.append(value))
encoder=OpusEncoderUtils(cfg['rate'],1,60)
tts.opus_encoder=encoder;tts.tts_timeout=5;tts.tts_stop_request=False;tts._correct_words_pattern=None
def fallback(*a,**kw):raise AssertionError('unexpected fallback')
tts.to_tts_stream=fallback
tts._longmemory_cosy_streaming_installed=False
client.install_cosyvoice_streaming(tts,conn)
guard.install_voice_interruption(u.Connection,u.receive,u.asr,u.send,tts_base_module=u.ttsbase)
async def run():
 loop=asyncio.get_running_loop();voiced=asyncio.Event()
 decoder=Decoder(cfg['rate'],1);started=time.perf_counter()
 async def socket(value):
  if isinstance(value,bytes):
   pcm=decoder.decode(bytes(value),cfg['rate']*60//1000)
   samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
   qualified=sum(abs(v)>=200 for v in samples)>=cfg['rate']*5//1000
   energy.append(qualified)
   wire.append((round((time.perf_counter()-started)*1000,3),'audio',conn.sentence_id))
   if qualified:voiced.set()
  else:
   msg=json.loads(value)
   wire.append((round((time.perf_counter()-started)*1000,3),msg.get('state',msg['type']),conn.sentence_id))
 conn.websocket.send=socket
 def callback(packet):
  produced.append(packet)
  asyncio.run_coroutine_threadsafe(u.ttsbase.sendAudioMessage(conn,'middle',packet,None,
      packet._longmemory_cosy_sentence_id),loop).result(3)
 old=loop.run_in_executor(None,lambda:tts.to_tts_stream('合成旧轮',opus_handler=callback))
 await asyncio.wait_for(voiced.wait(),4)
 assert any(energy)
 await u.asr.startToChat(conn,'合成识别交接')
 assert conn.client_abort is False and conn.sentence_id=='old'
 await asyncio.wait_for(old,3)
 assert all(packet._longmemory_cosy_cancelled() for packet in produced)
 old_count=sum(row[1]=='audio' for row in wire)
 stop_index=next(i for i,row in enumerate(wire) if row[1]=='stop')
 assert not any(row[1]=='audio' for row in wire[stop_index+1:])
 assert all(row['reader_stopped'] for row in reports)
 if cfg['mode']=='adaptive':assert reports[0]['outcome']=='cancelled'
 conn.sentence_id=tts.current_sentence_id='new'
 decoder=Decoder(cfg['rate'],1)
 new=loop.run_in_executor(None,lambda:tts.to_tts_stream('合成新轮',opus_handler=callback))
 await asyncio.wait_for(new,4)
 await asyncio.wait_for(u.send.send_tts_message(conn,'stop'),4)
 new_frames=sum(kind=='audio' and turn=='new' for _,kind,turn in wire)
 assert new_frames==20,(new_frames,wire)
 assert sum(energy[old_count:])==new_frames
 assert guard.snapshot(conn)['counts']['first_answer_send_returned']==2
 assert not conn.client_is_speaking
 assert 'torch' not in sys.modules
 return {'mode':cfg['mode'],'rate':cfg['rate'],'old_frames_before_formal_handoff':old_count,
  'old_frames_after_stop':0,'new_frames':new_frames,'first_old_decoded_frame_qualified':energy[0],
  'reader_stopped':all(row['reader_stopped'] for row in reports),'wire':wire,
  'device_playback_verified':False,'gpu_loaded':False}
try:print(json.dumps(asyncio.run(run())))
finally:encoder.close();dll.close()
'''


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed voice interpreter unavailable")
@pytest.mark.parametrize("mode", ["adaptive", "buffered"])
@pytest.mark.parametrize("rate", [16000, 24000])
def test_voiced_opus_then_formal_handoff_does_not_revive_old_audio_and_next_round_is_complete(mode, rate):
    calls = []
    def chunks(text, *, cancel_event, model_streaming, use_cache):
        calls.append(True)
        # 旧轮持续供给，让识别发生在有声之后、生产完成之前；新轮为完整1.2秒。
        count = 30 if len(calls) == 1 and mode == "adaptive" else 6
        for index in range(count):
            if cancel_event.wait(.025):
                return
            yield _wave(index * 4800, 4800)
    synth = NS(stream_chunks=chunks, stream_runtime=NS(applied=True, snapshot=lambda: {"active_requests": 0}))
    server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"root": str(ROOT), "voice": str(VOICE), "rate": rate, "mode": mode,
              "url": f"http://127.0.0.1:{server.server_address[1]}/v1/audio/stream"}
    try:
        result = subprocess.run([str(PYTHON), "-B", "-X", "utf8", "-c", DRIVER],
            input=json.dumps(config).encode(), capture_output=True, cwd=ROOT, timeout=18,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-3500:]
        report = json.loads(result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert report["first_old_decoded_frame_qualified"] is True
    assert report["new_frames"] == 20 and report["old_frames_after_stop"] == 0
    assert report["device_playback_verified"] is report["gpu_loaded"] is False
    assert len(calls) == 2
    print(json.dumps(report, ensure_ascii=False))
