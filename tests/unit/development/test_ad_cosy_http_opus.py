"""随机环回HTTP、合成波形和真实Opus；不加载权重、GPU或私人声音。"""

import io
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
from types import SimpleNamespace
import wave

import pytest

from test_cosyvoice_service import service

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
VOICE = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
PYTHON = VOICE / ".venv/Scripts/python.exe"

DRIVER = r'''
import json,math,os,sys,time
from pathlib import Path
from types import SimpleNamespace
config=json.load(sys.stdin)
voice=Path(config['voice']);sys.path.insert(0,str(voice))
opus=voice/'native/libopus-1.6.1/Library/bin'
os.environ['PATH']=str(opus)+os.pathsep+os.environ.get('PATH','')
dll=os.add_dll_directory(str(opus))
from core.utils.opus_encoder_utils import OpusEncoderUtils
from opuslib_next import Decoder
sys.path.insert(0,str(Path(config['source'])/'scripts/development/xiaozhi'))
import cosyvoice_streaming as client
client.STREAM_URL=config['url']
client.default_voice_active=lambda:False
reports=[];queued=[];packets=[];resets=[]
encoder=OpusEncoderUtils(config['rate'],1,60)
original_reset=encoder.reset_state
def reset():
 resets.append(True);original_reset()
encoder.reset_state=reset
def no_fallback(*args,**kwargs):raise AssertionError('unexpected fallback')
conn=SimpleNamespace(sample_rate=config['rate'],client_abort=False,sentence_id='synthetic-1',
 _longmemory_cosy_delivery_mode='adaptive',_longmemory_cosy_reply_cache=False,
 _longmemory_voice_latency=SimpleNamespace(record_continuity=lambda report,**kwargs:reports.append(report)),
 logger=SimpleNamespace(bind=lambda **kwargs:SimpleNamespace(warning=lambda text:None)))
tts=SimpleNamespace(to_tts_stream=no_fallback,tts_audio_queue=SimpleNamespace(put=queued.append),
 current_sentence_id=conn.sentence_id,_correct_words_pattern=None,opus_encoder=encoder,
 tts_timeout=5,tts_stop_request=False)
client.install_cosyvoice_streaming(tts,conn)
started=time.perf_counter()
def packet(value):
 packets.append({'at_ms':(time.perf_counter()-started)*1000,'packet':value})
 if config['cancel'] and len(packets)==3:conn.client_abort=True
try:
 tts.to_tts_stream('这是一段完全合成的连续音频回放。',opus_handler=packet)
 first_count=len(packets)
 if config['cancel']:
  conn.client_abort=False;conn.sentence_id=tts.current_sentence_id='synthetic-2'
  tts.to_tts_stream('这是取消后全新的一段回答。',opus_handler=lambda value:packets.append({'at_ms':0,'packet':value}))
 decoder=Decoder(config['rate'],1)
 decoded=[decoder.decode(row['packet'],config['rate']*60//1000) for row in packets]
 assert all(len(pcm)==config['rate']*60//1000*2 for pcm in decoded)
 assert 'torch' not in sys.modules
 print(json.dumps({'reports':reports,'first_count':first_count,'packets':len(packets),
  'resets':len(resets),'control_markers':len(queued),'first_ms':packets[0]['at_ms'],
  'cancel_late_packets':first_count-3 if config['cancel'] else None,'gpu_loaded':False}))
finally:
 encoder.close();dll.close()
'''


def _wave(start, size):
    values = [int(12000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(start, start + size)]
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(struct.pack("<" + "h" * size, *values))
    return output.getvalue()


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed voice interpreter unavailable")
@pytest.mark.parametrize("rate", [16000, 24000])
@pytest.mark.parametrize("cancel", [False, True])
def test_adaptive_real_http_fir_opus_eos_and_cancel_next_turn(rate, cancel):
    calls = []
    sizes = [1081, 3779, 8100, 5039]
    chunks, start = [], 0
    for size in sizes:
        chunks.append(_wave(start, size))
        start += size
    def stream(text, *, cancel_event, model_streaming, use_cache):
        calls.append((model_streaming, use_cache))
        for chunk, pause in zip(chunks, [.02, .03, .15, .1]):
            if cancel_event.wait(pause):
                return
            yield chunk
    synth = SimpleNamespace(stream_chunks=stream,
        stream_runtime=SimpleNamespace(applied=True, snapshot=lambda: {"active_requests": 0}))
    server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"voice": str(VOICE), "source": str(ROOT), "rate": rate, "cancel": cancel,
              "url": f"http://127.0.0.1:{server.server_address[1]}/v1/audio/stream"}
    try:
        result = subprocess.run([str(PYTHON), "-B", "-X", "utf8", "-c", DRIVER],
            input=json.dumps(config).encode(), capture_output=True, cwd=ROOT, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-2500:]
        report = json.loads(result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    expected_frames = math.ceil(math.ceil(sum(sizes) * rate / 24000) / (rate * .06))
    assert report["packets"] == expected_frames + (3 if cancel else 0)
    assert report["first_count"] == (3 if cancel else expected_frames)
    assert report["cancel_late_packets"] == (0 if cancel else None)
    assert all(row["reader_stopped"] for row in report["reports"])
    assert report["reports"][-1]["outcome"] == "completed"
    assert report["reports"][-1]["received_audio_ms"] == pytest.approx(math.ceil(sum(sizes) * rate / 24000) / rate * 1000)
    assert report["reports"][-1]["max_underflow_ms"] == 0
    assert report["reports"][-1]["client_receive_rtf"] > 0
    assert report["control_markers"] == (2 if cancel else 1)
    assert report["resets"] == (1 if cancel else 0)
    assert all(streaming and not cached for streaming, cached in calls)
    print(json.dumps({"rate": rate, "cancel": cancel, **report}, ensure_ascii=False))


@pytest.mark.parametrize("buffered_pcm", [False, True])
def test_cancel_before_first_audio_closes_blocked_reader_and_server_gate(buffered_pcm):
    import sys
    sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
    import cosyvoice_streaming as client
    entered, cleaned, cancelled = threading.Event(), threading.Event(), threading.Event()
    errors, delivered = [], []
    def stream(_text, *, cancel_event, **_kwargs):
        try:
            entered.set()
            if buffered_pcm:
                yield _wave(0, 1440)
            assert cancel_event.wait(2), "peer socket did not close"
            raise service._stream_runtime.StreamCancelled()
        finally:
            cleaned.set()
    synth = SimpleNamespace(stream_chunks=stream,
        stream_runtime=SimpleNamespace(applied=True, snapshot=lambda: {"active_requests": 0}))
    server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    def source(stop):
        with client._open_stream(f"http://127.0.0.1:{server.server_address[1]}/v1/audio/stream",
                json={"input": "合成取消边界", "stream": True, "delivery_mode": "incremental", "cache": False},
                timeout=(1, 2), headers={}, cancelled=stop) as response:
            decoder = client.ContinuousPCM(24000)
            for wav in client.iter_wav_chunks(response.raw, require_end=True):
                yield decoder.feed(wav)
            yield decoder.finish()
    buffer = client.AdaptivePCMBuffer(source, 24000, cancelled.is_set, client.PlaybackTimeline())
    def consume():
        try:
            delivered.extend(buffer)
        except client._SpeechCancelled:
            errors.append("cancelled")
        finally:
            buffer.close()
    consumer = threading.Thread(target=consume)
    consumer.start()
    try:
        assert entered.wait(1)
        if buffered_pcm:
            # 等队列实际持有PCM，而不是仅证明服务已进入生成器。
            import time
            deadline = time.monotonic() + 1
            while buffer.peak_frames == 0 and time.monotonic() < deadline:
                threading.Event().wait(.002)
            assert buffer.peak_frames == 1
        cancelled.set()
        consumer.join(1)
        assert not consumer.is_alive()
        assert cleaned.wait(1)
        assert not delivered and errors == ["cancelled"]
        assert buffer.snapshot()["reader_stopped"]
        assert server.generation_gate.acquire(timeout=1), "generation gate was not released"
        server.generation_gate.release()
    finally:
        cancelled.set()
        buffer.close()
        consumer.join(1)
        server.shutdown()
        server.server_close()
        serving.join(2)
