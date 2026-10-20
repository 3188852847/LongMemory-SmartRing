"""真实HTTP/重采样/Opus基准路径的CPU契约，避免GPU窗口才发现驱动错误。"""
import io
import json
from pathlib import Path
import struct
import subprocess
import threading
import wave
from types import SimpleNamespace

import pytest

from test_cosyvoice_service import service

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT.parents[2] if ROOT.parent.name == 'worktrees' else ROOT
VOICE = MAIN / 'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server'
PYTHON = VOICE / '.venv/Scripts/python.exe'


def _wave(samples):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(struct.pack('<h', 5000) * samples)
    return output.getvalue()


@pytest.mark.skipif(not PYTHON.is_file(), reason='owner-installed voice interpreter unavailable')
@pytest.mark.parametrize('segmented', [False, True])
@pytest.mark.parametrize('mode', ['buffered', 'incremental'])
def test_real_client_benchmark_preserves_daily_segmentation_and_exact_frames(segmented, mode):
    calls = []
    chunks = [_wave(size) for size in (720, 1800, 840)]

    def stream(text, **kwargs):
        calls.append((text, kwargs['use_cache'], kwargs['model_streaming']))
        yield from chunks

    synth = SimpleNamespace(stream_chunks=stream,
        stream_runtime=SimpleNamespace(applied=True, snapshot=lambda: {'active_requests': 0}))
    server = service.CosyVoiceHTTPServer(('127.0.0.1', 0), synth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {'source_root': str(ROOT), 'voice_root': str(VOICE), 'mode': mode,
        'url': f'http://127.0.0.1:{server.server_address[1]}/v1/audio/stream',
        'text': '下午的阳光落在窗边。我们可以先整理桌面，再慢慢安排接下来的事情。',
        'cache': False, 'sample_rate': 16000, 'segmented': segmented}
    try:
        result = subprocess.run([str(PYTHON), '-B', '-X', 'utf8',
            str(ROOT / 'scripts/development/cosyvoice/benchmark_stream_client.py')],
            input=json.dumps(config).encode(), capture_output=True, cwd=ROOT,
            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-1500:]
        row = json.loads(result.stdout)['rounds'][0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert len(calls) == (2 if segmented else 1)
    assert ''.join(text for text, _, _ in calls) == config['text']
    assert all(not cached and streaming == (mode == 'incremental') for _, cached, streaming in calls)
    assert row['opus_frames'] == 3 * len(calls)
    assert row['audio_ms'] == 140 * len(calls)
    assert len(row['chunks']) == 3 * len(calls)
    assert row['first_opus_ms'] >= row['first_pcm_ms']
    assert row['segmented'] is segmented
    assert len(row['segments']) == (len(calls) if segmented else 0)
