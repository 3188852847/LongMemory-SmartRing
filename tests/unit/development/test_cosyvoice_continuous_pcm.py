"""借用已安装3.10音频依赖做CPU重采样及真实Opus检查；不加载torch/CUDA。"""
import json
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[3]
MAIN=ROOT.parents[2] if ROOT.parent.name=='worktrees' else ROOT
VOICE=MAIN/'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server'
PYTHON=VOICE/'.venv/Scripts/python.exe'


@pytest.mark.skipif(not PYTHON.is_file(),reason='owner-installed voice interpreter unavailable')
def test_continuous_fir_matches_whole_reference_and_real_opus_frames():
    driver=r'''
import io,json,math,os,sys,wave
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
sys.path.insert(0,sys.argv[1])
from cosyvoice_streaming import ContinuousPCM
voice=Path(sys.argv[2]);sys.path.insert(0,str(voice))
opus=voice/'native/libopus-1.6.1/Library/bin'
os.environ['PATH']=str(opus)+os.pathsep+os.environ.get('PATH','');dll=os.add_dll_directory(str(opus))
from core.utils.opus_encoder_utils import OpusEncoderUtils
from opuslib_next import Decoder
def wav(samples):
 out=io.BytesIO()
 with wave.open(out,'wb') as stream:
  stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(24000);stream.writeframes(samples.astype('<i2').tobytes())
 return out.getvalue()
rng=np.random.default_rng(6015);cases=0
for length in (1,2,3,17,239,1440,2401,48019):
 values=rng.integers(-18000,18000,length,dtype=np.int16)
 for rate in (16000,24000):
  converter=ContinuousPCM(rate);pieces=[];index=0
  for size in (1,2,7,31,61,509,1440,2401,length):
   block=values[index:index+size]
   if len(block):pieces.append(converter.feed(wav(block)));index+=len(block)
  assert index==length
  pieces.append(converter.finish());actual=np.frombuffer(b''.join(pieces),dtype='<i2')
  divisor=math.gcd(rate,24000)
  expected=values if rate==24000 else np.rint(np.clip(resample_poly(values.astype(np.float64),rate//divisor,24000//divisor),-32768,32767)).astype('<i2')
  assert len(actual)==len(expected) and np.max(np.abs(actual.astype(int)-expected.astype(int)))<=1,(length,rate)
  encoder=OpusEncoderUtils(rate,1,60);packets=[]
  try:
   for pcm in pieces[:-1]:
    if pcm:encoder.encode_pcm_to_opus_stream(pcm,False,packets.append)
   encoder.encode_pcm_to_opus_stream(pieces[-1],True,packets.append)
  finally:encoder.close()
  expected_frames=math.ceil(len(expected)/(rate*60//1000));assert len(packets)==expected_frames
  decoder=Decoder(rate,1);decoded=[decoder.decode(packet,rate*60//1000) for packet in packets]
  assert all(len(block)==rate*60//1000*2 for block in decoded)
  assert expected_frames*rate*60//1000-len(expected)<rate*60//1000
  cases+=1
dll.close();print(json.dumps({'cases':cases,'real_opus':True,'scipy_reference_max_error_lsb':1,'gpu_loaded':False}))
'''
    result=subprocess.run([str(PYTHON),'-B','-X','utf8','-c',driver,
        str(ROOT/'scripts/development/xiaozhi'),str(VOICE)],capture_output=True,cwd=ROOT,
        timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')[-2500:]
    assert json.loads(result.stdout)['cases']==16
