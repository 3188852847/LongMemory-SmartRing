"""固定074ca6d原始控制流：没有finally适配时取消也必须耗尽并释放请求状态。"""
from contextlib import closing
import http.client
from pathlib import Path
import socket
import threading
import time
from types import MethodType, SimpleNamespace as NS
import uuid

import numpy as np
import pytest

from test_cosyvoice_service import service
from test_cosyvoice_stream_runtime import Tensor, runtime

ROOT = Path(__file__).resolve().parents[3]


def unadapted_case(*, kind='unsupported', phase='normal', force=False, parts=1, hold=False):
    cancel = threading.Event()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    workers, modes = [], []
    torch = NS(zeros=lambda *shape, **kw: Tensor(shape=shape), int32='int32',
        tensor=lambda values: Tensor(values), cuda=NS(is_available=lambda: False))
    namespace = {'torch': torch, 'uuid': uuid, 'threading': threading, 'time': time, 'np': np}
    fixture = ROOT / 'tests/fixtures/cosyvoice_tts_074ca6d.py'
    exec(compile(fixture.read_text(encoding='utf-8'), str(fixture), 'exec'), namespace)

    class Model:
        def __init__(self):
            self.lock = threading.Lock()
            self.tts_speech_token_dict, self.llm_end_dict, self.hift_cache_dict = {}, {}, {}
            self.token_hop_len, self.token_max_hop_len, self.stream_scale_factor = 25, 100, 2
            self.flow = NS(pre_lookahead_len=3)

        def llm_job(self, *args):
            key = args[-1]
            workers.append(threading.current_thread())
            started.set()
            try:
                if hold:
                    assert release.wait(3), 'test producer was not released'
                for index in range(40):
                    self.tts_speech_token_dict[key].append(index)
                    if phase == 'during_model':
                        cancel.set()
            finally:
                self.llm_end_dict[key] = True
                finished.set()

        def token2wav(self, **kwargs):
            if phase == 'before_upstream_yield':
                cancel.set()
            return Tensor(shape=(1, 100))

    model = Model()
    model.tts = MethodType(namespace['tts'], model)  # 原始函数，绝不安装finally变换。
    synth = object.__new__(service.CosyVoiceSynthesizer)
    synth._lock = threading.Lock()
    synth._stream_cache = service.OrderedDict()
    synth._cache_entries = 4
    synth._model = NS(model=model)
    synth.stream_token_hop_len = 25
    synth.model_streaming = True  # 验证legacy配置不能绕过未适配保护。
    synth.force_buffered_audio = force
    if kind == 'unsupported':
        synth.stream_runtime = runtime.install_stream_runtime(model)
        assert synth.stream_runtime.applied is False
        synth.stream_runtime.external_cancel = 'untouched'
    elif kind == 'no_applied':
        synth.stream_runtime = NS(external_cancel='untouched')

    def inference(_text, _context, *, model_streaming):
        for _ in range(parts):
            modes.append(model_streaming)
            yield from model.tts(stream=model_streaming)

    def wave(_speech):
        if phase == 'during_wave':
            cancel.set()
        if phase == 'wave_error':
            raise ValueError('synthetic_wave_error')
        return b'RIFF-synthetic'

    synth._inference = inference
    synth._wave_bytes = wave
    return NS(synth=synth, model=model, cancel=cancel, started=started, release=release,
        finished=finished, workers=workers, modes=modes)


def assert_clean(case):
    assert not case.model.tts_speech_token_dict
    assert not case.model.llm_end_dict
    assert not case.model.hift_cache_dict
    assert all(not thread.is_alive() for thread in case.workers)
    assert case.model.lock.acquire(blocking=False)
    case.model.lock.release()
    assert case.synth._lock.acquire(blocking=False)
    case.synth._lock.release()
    guard = getattr(case.synth, 'stream_runtime', None)
    if guard is not None:
        assert guard.external_cancel == 'untouched'


@pytest.mark.parametrize('kind', ['missing', 'no_applied', 'unsupported'])
@pytest.mark.parametrize('phase', ['before_call', 'during_model', 'before_upstream_yield', 'during_wave'])
def test_unadapted_cancel_exhausts_real_upstream_before_releasing_lock(kind, phase):
    case = unadapted_case(kind=kind, phase=phase, parts=2)
    if phase == 'before_call':
        case.cancel.set()
    iterator = case.synth.stream_chunks('合成检查', use_cache=True,
        model_streaming=True, cancel_event=case.cancel)
    with pytest.raises(service._stream_runtime.StreamCancelled):
        list(iterator)
    assert_clean(case)
    assert not case.synth._stream_cache
    assert case.modes == ([] if phase == 'before_call' else [False, False])
    # 同一服务下一话轮必须可完成，旧cancel也没有挂入未适配guard。
    case.cancel.clear()
    case.synth._wave_bytes = lambda _speech: b'next-round'
    assert list(case.synth.stream_chunks('新轮次', use_cache=False)) == [b'next-round'] * 2
    assert_clean(case)


@pytest.mark.parametrize('force', [False, True])
def test_unadapted_buffered_close_and_cache_never_leave_upstream_suspended(force):
    case = unadapted_case(force=force, parts=2)
    stream = case.synth.stream_chunks('缓存检查', use_cache=True, model_streaming=True)
    assert next(stream) == b'RIFF-synthetic'
    assert not case.model.tts_speech_token_dict  # 首次交付前已经耗尽原始函数。
    stream.close()
    assert_clean(case)
    assert list(case.synth.stream_chunks('缓存检查')) == [b'RIFF-synthetic'] * 2
    calls = len(case.workers)
    cached = case.synth.stream_chunks('缓存检查', cancel_event=case.cancel)
    assert next(cached) == b'RIFF-synthetic'
    case.cancel.set()
    with pytest.raises(service._stream_runtime.StreamCancelled):
        next(cached)
    assert len(case.workers) == calls
    assert_clean(case)


def test_unadapted_wave_packaging_error_also_exhausts_original_cleanup():
    case = unadapted_case(phase='wave_error', parts=2)
    with pytest.raises(ValueError, match='synthetic_wave_error'):
        list(case.synth.stream_chunks('合成检查'))
    assert case.modes == [False, False]
    assert_clean(case)


@pytest.mark.parametrize('version2', [False, True])
@pytest.mark.parametrize('force', [False, True])
def test_unadapted_http_peer_close_drains_before_gate_releases(version2, force):
    case = unadapted_case(force=force, hold=True)
    original = case.synth.stream_chunks
    received_cancel = []

    def stream(*args, **kwargs):
        received_cancel.append(kwargs.get('cancel_event'))
        yield from original(*args, **kwargs)

    case.synth.stream_chunks = stream
    server = service.CosyVoiceHTTPServer(('127.0.0.1', 0), case.synth)
    owner = threading.Thread(target=server.serve_forever, daemon=True)
    owner.start()
    import json
    body = {'input': '合成检查', 'stream': True, 'cache': False}
    if version2:
        body['delivery_mode'] = 'buffered'
    payload = json.dumps(body).encode()
    response = None
    try:
        with closing(socket.create_connection(server.server_address, timeout=2)) as peer:
            peer.sendall(b'POST /v1/audio/stream HTTP/1.0\r\nHost: 127.0.0.1\r\n'
                b'Content-Type: application/json\r\nContent-Length: '
                + str(len(payload)).encode() + b'\r\n\r\n' + payload)
            response = http.client.HTTPResponse(peer)
            response.begin()
            assert response.status == 200 and case.started.wait(2)
            assert server.generation_gate.locked()
            peer.shutdown(socket.SHUT_RDWR)
            response.close()
            if version2:
                assert received_cancel[0].wait(2)
            else:
                assert received_cancel == [None]
            assert server.generation_gate.locked()  # 不提前释放后让旧生产者污染新轮次。
            case.release.set()
        deadline = time.monotonic() + 2
        while server.generation_gate.locked() and time.monotonic() < deadline:
            threading.Event().wait(.005)
        assert not server.generation_gate.locked()
        assert case.modes == [False]
        assert_clean(case)
        assert not any(t.name == 'cosyvoice-peer-close' for t in threading.enumerate())
    finally:
        case.release.set()
        if response is not None:
            response.close()
        server.shutdown()
        server.server_close()
        owner.join(timeout=2)
