"""使用合成器替身验证 CosyVoice 本机 HTTP 边界，不加载模型或 CUDA。"""

import argparse
import http.client
import importlib.util
import json
from pathlib import Path
import struct
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "scripts/development/cosyvoice"
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location("cosyvoice_service_test", DIRECTORY / "service.py")
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)
sys.path.pop(0)


class FakeSynthesizer:
    load_seconds = 9.0
    warmup_seconds = 3.0
    stream_token_hop_len = 25
    reference_cached = True
    runtime_info = {"hidden_only": True, "torch_threads": 16}

    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, use_cache=True):
        self.calls.append((text, use_cache))
        return b"RIFF-cosyvoice-wave"

    def stream_chunks(self, text, *, use_cache=True):
        self.calls.append((text, "stream", use_cache))
        yield b"RIFF-stream-one"
        yield b"RIFF-stream-two"


def test_v2_stream_has_explicit_end_and_closes_generator(local_service):
    port,synth=local_service;closed=[];seen=[]
    synth.stream_runtime=SimpleNamespace(applied=True,snapshot=lambda:{'active_requests':0})
    def chunks(text,**kwargs):
        seen.append(kwargs)
        try:yield b'first';yield b'second'
        finally:closed.append(True)
    synth.stream_chunks=chunks
    status,content,body=request(port,'POST','/v1/audio/stream',
        {'input':'合成协议检查','stream':True,'delivery_mode':'incremental','cache':False})
    assert status==200 and body==struct.pack('!I',5)+b'first'+struct.pack('!I',6)+b'second'+b'\0'*4
    assert seen[0]['model_streaming'] is True and seen[0]['use_cache'] is False and closed==[True]


@pytest.mark.parametrize('mode',[[],{},False,'unrecognized'])
def test_v2_delivery_mode_rejects_invalid_values(local_service,mode):
    port,synth=local_service
    status,_,_=request(port,'POST','/v1/audio/stream',{'input':'合成','stream':True,'delivery_mode':mode})
    assert status==400 and not synth.calls


def test_v2_client_cancel_breaks_read_and_releases_generation_gate(local_service):
    import socket
    cosy_directory=ROOT/'scripts/development/xiaozhi'
    sys.path.insert(0,str(cosy_directory))
    try:
        spec=importlib.util.spec_from_file_location('cancel_http_stream',cosy_directory/'cosyvoice_streaming.py')
        client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
    finally:sys.path.pop(0)
    port,synth=local_service;closed=threading.Event()
    synth.stream_runtime=SimpleNamespace(applied=True,snapshot=lambda:{'active_requests':0})
    def chunks(_text,*,cancel_event,**kwargs):
        try:
            yield b'first'
            assert cancel_event.wait(2),'server did not observe own peer close'
            raise service._stream_runtime.StreamCancelled()
        finally:closed.set()
    synth.stream_chunks=chunks
    cancel=threading.Event()
    with client._open_stream(f'http://127.0.0.1:{port}/v1/audio/stream',
            json={'input':'合成取消','stream':True,'delivery_mode':'incremental'},
            timeout=(1,4),headers={},cancelled=cancel.is_set) as response:
        iterator=client.iter_wav_chunks(response.raw,require_end=True)
        assert next(iterator)==b'first'
        cancel.set()
        with pytest.raises((EOFError,OSError,http.client.HTTPException)):next(iterator)
    assert closed.wait(2)
    # 释放锁之后才允许下一个合成；没有残留HTTP观察线程。
    assert not any(thread.name=='cosyvoice-http-cancel' and thread.is_alive() for thread in threading.enumerate())


def test_selected_voice_warmup_uses_real_stream_and_never_populates_reply_cache():
    synth=object.__new__(service.CosyVoiceSynthesizer);calls=[]
    synth._profiles=SimpleNamespace(model_context=lambda:({},None,'selected-identity'))
    synth.stream_runtime=SimpleNamespace(applied=True)
    def stream(text,**kwargs):calls.append((text,kwargs));yield b'synthetic'
    synth.stream_chunks=stream
    assert synth.prepare_selected_voice()>=0
    assert calls==[(service.WARMUP_TEXT,{'use_cache':False,'model_streaming':True})]
    assert synth.selected_warmup_identity=='selected-identity'


def test_selected_voice_change_during_explicit_warmup_is_not_declared_ready():
    synth=object.__new__(service.CosyVoiceSynthesizer)
    identities=iter(('old','new'))
    synth._profiles=SimpleNamespace(model_context=lambda:({},None,next(identities)))
    synth.stream_runtime=SimpleNamespace(applied=True)
    synth.stream_chunks=lambda *a,**kw:iter((b'synthetic',))
    with pytest.raises(RuntimeError,match='changed_during_warmup'):synth.prepare_selected_voice()


@pytest.mark.parametrize("system_qos,applied", [(False, True), (False, False), (True, False)])
def test_main_applies_qos_before_model_and_exposes_result(monkeypatch, system_qos, applied):
    events = []
    result = {"applied": applied, "reason": "applied" if applied else "unsupported",
              "before": None, "after": None}
    qos_module = ModuleType("windows_qos")

    def configure():
        events.append("qos")
        return result

    qos_module.apply_current_process_high_qos = configure
    monkeypatch.setitem(sys.modules, "windows_qos", qos_module)
    synth = SimpleNamespace(runtime_info={}, load_seconds=0, warmup_seconds=0)

    def create_synth(*args, **kwargs):
        events.append("model")
        return synth

    class Server:
        def __init__(self, address, selected):
            assert selected is synth
            assert "windows_qos" in selected.runtime_info
            events.append("server")

        def serve_forever(self, **kwargs):
            events.append("serve")

        def server_close(self):
            events.append("close")

    monkeypatch.setattr(service, "CosyVoiceSynthesizer", create_synth)
    monkeypatch.setattr(service, "CosyVoiceHTTPServer", Server)
    monkeypatch.setattr(sys, "argv", ["service.py"] + (["--system-qos"] if system_qos else []))
    service.main()
    assert events == ([] if system_qos else ["qos"]) + ["model", "server", "serve", "close"]
    if system_qos:
        assert synth.runtime_info["windows_qos"]["reason"] == "disabled"
    else:
        assert synth.runtime_info["windows_qos"] is result


@pytest.fixture
def local_service():
    synth = FakeSynthesizer()
    server = service.CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], synth
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    payload = None if body is None else json.dumps(body).encode()
    final_headers = dict(headers or {})
    if payload is not None:
        final_headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=payload, headers=final_headers)
    response = connection.getresponse()
    result = response.status, response.getheader("Content-Type"), response.read()
    connection.close()
    return result


def test_health_capabilities_and_synthesis_contract(local_service):
    port, synth = local_service
    status, _, body = request(port, "GET", "/health")
    health = json.loads(body)
    assert status == 200 and health["provider"] == "cosyvoice3"
    assert health["load_seconds"] == 9.0 and health["warmup_seconds"] == 3.0
    assert health["stream_token_hop_len"] == 25
    assert health["reference_cached"] is True
    assert health["runtime"] == {"hidden_only": True, "torch_threads": 16}
    assert health["capabilities"]["delivery_modes"] == ["buffered", "audio_stream"]
    assert health["capabilities"]["cancellation"] == "cooperative"

    status, content_type, body = request(port, "POST", "/v1/audio/speech", {
        "input": "  合成测试  ", "response_format": "wav", "stream": False,
        "cache": False, "voice": "ignored-upstream-field",
    })
    assert status == 200 and content_type == "audio/wav"
    assert body == b"RIFF-cosyvoice-wave"
    assert synth.calls == [("合成测试", False)]

    status, content_type, body = request(port, "POST", "/v1/audio/stream", {
        "input": "分块测试", "response_format": "wav", "stream": True, "cache": False,
    })
    assert status == 200 and content_type == "application/vnd.longmemory.wav-chunks"
    first_size = struct.unpack("!I", body[:4])[0]
    assert body[4:4 + first_size] == b"RIFF-stream-one"
    second_offset = 4 + first_size
    second_size = struct.unpack("!I", body[second_offset:second_offset + 4])[0]
    assert body[second_offset + 4:second_offset + 4 + second_size] == b"RIFF-stream-two"
    assert synth.calls[-1] == ("分块测试", "stream", False)


@pytest.mark.parametrize("adapted,forced,restart,usable", [
    (False, False, False, False), (True, False, False, True),
    (True, True, False, False), (True, False, True, False),
])
def test_capability_distinguishes_protocol_instance_and_incremental(local_service, adapted, forced, restart, usable):
    port, synth = local_service
    synth.stream_runtime = SimpleNamespace(applied=adapted)
    synth.force_buffered_audio = forced
    synth.requires_restart = restart
    synth.selected_warmup_identity = "context-only-digest"
    synth._profiles = SimpleNamespace(profile=lambda: ({}, "config-only-digest"),
        model_context=lambda: (None, None, "context-only-digest"))
    status, _, body = request(port, "GET", "/v1/capabilities")
    caps = json.loads(body)
    assert status == 200 and not synth.calls
    stream = caps["audio_stream"]
    assert stream["protocol"]["supported"] and stream["protocol"]["version"] == 2
    assert stream["protocol"]["sample_rate_hz"] == 24000
    assert stream["instance_usable"] is (not restart)
    assert stream["incremental_usable"] is usable
    assert stream["default_delivery_mode"] == "buffered"
    assert stream["profile_identity"]["selected_voice_warm"]
    assert stream["profile_identity"]["config_digest"] != stream["profile_identity"]["context_digest"]
    assert stream["cancellation"] == ("token-boundary-and-join" if adapted else "drain-before-reuse")


def test_speech_ids_are_server_generated_and_stream_failure_does_not_mean_completed(local_service):
    port, synth = local_service
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    supplied_round = "a" * 24
    connection.request("POST", "/v1/audio/stream", body=json.dumps({"input": "private synthetic text", "stream": True}),
        headers={"Content-Type": "application/json", "X-Voice-Round-Id": supplied_round, "X-Request-Id": "forged-secret"})
    response = connection.getresponse()
    request_id = response.getheader("X-Request-Id")
    assert request_id != "forged-secret" and len(request_id) == 24
    assert response.getheader("X-Voice-Round-Id") == supplied_round
    response.read()
    connection.close()
    health = json.loads(request(port, "GET", "/health")[2])
    row = next(row for row in health["speech_requests"] if row["request_id"] == request_id)
    assert row["voice_round_id"] == supplied_round and row["association"] == "local_caller_claim"
    assert row["stages"] == ["request_received", "synthesis_entered", "synthesis_returned", "response_written"]
    assert row["device_playback"] == "unconfirmed" and "private" not in json.dumps(health)

    def failed(*args, **kwargs):
        yield b"synthetic-first-chunk"
        raise TimeoutError("private-model-secret")
    synth.stream_chunks = failed
    status, _, _ = request(port, "POST", "/v1/audio/stream", {"input": "private text", "stream": True})
    assert status == 200  # 响应头早已发出；不能冒充完整生成成功。
    latest = json.loads(request(port, "GET", "/health")[2])["speech_requests"][0]
    assert "synthesis_failed" in latest["stages"] and "synthesis_returned" not in latest["stages"]
    assert "private" not in json.dumps(latest)


def test_only_signed_round_headers_emit_service_events(local_service, monkeypatch):
    observer = service._voice_observation
    events = []
    written = threading.Event()
    def emit(event):
        events.append(event)
        if event['event'] == 'tts_service_written':
            written.set()
    monkeypatch.setenv("LONGMEMORY_RUNTIME_TOKEN", "a" * 64)
    monkeypatch.setattr(observer, "emit", emit)
    headers = observer.VoiceRound().headers()
    port, _ = local_service
    request(port, "POST", "/v1/audio/speech", {"input": "private text"}, headers)
    # Content-Length读取完成并不保证服务线程已执行紧随write之后的观测事件。
    assert written.wait(1)
    assert {event["event"] for event in events} == {
        "tts_service_entered", "tts_service_returned", "tts_service_written"}
    assert all(event["round_id"] == headers["X-Voice-Round-Id"] and event["source"] == "cosyvoice" for event in events)
    assert "X-Voice-Round-Proof" not in json.dumps(events) and "private" not in json.dumps(events)
    events.clear()
    request(port, "POST", "/v1/audio/speech", {"input": "ok"}, {**headers, "X-Voice-Round-Proof": "invalid"})
    assert events == []


@pytest.mark.parametrize("body", [
    {}, {"input": ""}, {"input": "x" * 601},
    {"input": "ok", "response_format": "mp3"}, {"input": "ok", "stream": True},
])
def test_rejects_invalid_requests(local_service, body):
    assert request(local_service[0], "POST", "/v1/audio/speech", body)[0] == 400


@pytest.mark.parametrize("body", [
    {"input": "ok"}, {"input": "ok", "stream": False}, {"input": "ok", "stream": "yes"},
])
def test_stream_endpoint_requires_explicit_boolean_stream(local_service, body):
    assert request(local_service[0], "POST", "/v1/audio/stream", body)[0] == 400


def test_rejects_browser_origin_and_non_loopback(local_service):
    status, _, _ = request(
        local_service[0], "POST", "/v1/audio/speech", {"input": "ok"},
        {"Origin": "https://example.invalid"},
    )
    assert status == 403
    with pytest.raises(argparse.ArgumentTypeError):
        service.loopback_address("192.168.1.2")


def test_stream_preparation_restores_initial_model_hop():
    synth = object.__new__(service.CosyVoiceSynthesizer)
    runtime = type("Runtime", (), {"token_hop_len": 100})()
    synth._model = type("Cosy", (), {"model": runtime})()
    synth.stream_token_hop_len = 25
    synth._prepare_stream()
    assert runtime.token_hop_len == 25


@pytest.mark.parametrize("model_streaming", [False, True])
def test_stream_uses_cached_reference_and_resets_hop_before_inference(model_streaming):
    calls = []

    class Model:
        model = type("Runtime", (), {"token_hop_len": 100})()

        def inference_zero_shot(self, *args, **kwargs):
            calls.append((args, kwargs, self.model.token_hop_len))
            yield {"tts_speech": object()}

    synth = object.__new__(service.CosyVoiceSynthesizer)
    synth._model = Model()
    synth._lock = threading.Lock()
    synth._stream_cache = service.OrderedDict()
    synth._cache_entries = 4
    synth._prompt_wav = Path("fixed-reference.wav")
    synth.stream_token_hop_len = 25
    synth.model_streaming = model_streaming
    synth.stream_runtime = SimpleNamespace(applied=True)
    synth._wave_bytes = lambda _speech: b"RIFF-chunk"

    assert list(synth.stream_chunks("短句")) == [b"RIFF-chunk"]
    args, kwargs, hop_at_call = calls[0]
    assert args == ("短句", service.PROMPT_TEXT, synth._prompt_wav)
    assert kwargs == {
        "zero_shot_spk_id": service.REFERENCE_SPEAKER_ID,
        "stream": model_streaming,
    }
    assert hop_at_call == 25

    # 第二次完全相同的回答复用进程内 WAV 块，不再调用模型。
    assert list(synth.stream_chunks("短句")) == [b"RIFF-chunk"]
    assert len(calls) == 1


def test_complete_segment_exhausts_model_before_http_consumer_can_disconnect():
    state = []

    class Model:
        model = type("Runtime", (), {"token_hop_len": 100})()

        def inference_zero_shot(self, *_args, **_kwargs):
            yield {"tts_speech": object()}
            # 模拟上游仅在最后 yield 之后清理请求状态。
            state.append("cleaned")

    synth = object.__new__(service.CosyVoiceSynthesizer)
    synth._model = Model()
    synth._lock = threading.Lock()
    synth._stream_cache = service.OrderedDict()
    synth._cache_entries = 4
    synth._prompt_wav = Path("fixed-reference.wav")
    synth.stream_token_hop_len = 25
    synth.model_streaming = False
    synth._wave_bytes = lambda _speech: b"RIFF-chunk"
    stream = synth.stream_chunks("短句")
    assert next(stream) == b"RIFF-chunk"
    assert state == ["cleaned"]
    stream.close()
    assert synth._lock.acquire(blocking=False)
    synth._lock.release()


@pytest.fixture
def constructor_runtime(monkeypatch):
    """只替换构造器的外部依赖；服务自己的初始化顺序与状态生成保持真实。"""
    state = SimpleNamespace(validations=[], registrations=[], warmups=[], installations=[])
    state.encoder = SimpleNamespace(forward_one_step=lambda *_args: "original")
    state.runtime = SimpleNamespace(
        llm=SimpleNamespace(llm=state.encoder), fp16=True, token_hop_len=25,
    )
    state.frontend = SimpleNamespace(text_frontend="wetext")
    state.prompt = Path("synthetic-reference.wav")

    def validate(source_root, model_dir):
        state.validations.append((source_root, model_dir))
        return {"prompt_wav": state.prompt}

    class FakeCosyVoice3:
        sample_rate = 24000

        def __init__(self, model_dir, *, fp16):
            state.model_arguments = (model_dir, fp16)
            self.model = state.runtime
            self.frontend = state.frontend

        def add_zero_shot_spk(self, text, wave, speaker_id):
            state.registrations.append((text, wave, speaker_id))
            return True

        def list_available_spks(self):
            return [service.REFERENCE_SPEAKER_ID]

    def warmup(synth, text):
        # 验证优化选择与模式信息在暖机前已准备好，不实际加载或执行模型。
        state.warmups.append((text, synth.model_streaming, dict(synth.runtime_info)))
        return b"synthetic-warmup"

    # syspath_prepend 同时让 monkeypatch 在结束时恢复 service 构造器插入的路径。
    monkeypatch.syspath_prepend(str(DIRECTORY))
    monkeypatch.setattr(service, "validate_local_files", validate)
    monkeypatch.setattr(service, "configure_runtime_cache", lambda: None)
    monkeypatch.setattr(service.CosyVoiceSynthesizer, "_generate", warmup)
    monkeypatch.setitem(sys.modules, "soundfile", ModuleType("soundfile"))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        __version__="2.3.1+cu121", cuda=SimpleNamespace(is_available=lambda: True),
        get_num_threads=lambda: 16, get_num_interop_threads=lambda: 24,
    ))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(__version__="4.51.3"))
    for name in ("cosyvoice", "cosyvoice.cli"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, "cosyvoice.cli.cosyvoice", SimpleNamespace(CosyVoice3=FakeCosyVoice3))
    spec = importlib.util.spec_from_file_location(
        "cosyvoice_constructor_optimizations", DIRECTORY / "runtime_optimizations.py",
    )
    state.optimizations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(state.optimizations)
    monkeypatch.setitem(sys.modules, "runtime_optimizations", state.optimizations)

    def install(encoder):
        state.installations.append(encoder)
        return SimpleNamespace(applied=True, reason="qwen2_unused_text_head_bypassed")

    state.install = install
    return state


def constructor_health(synth):
    """复用真实 health 处理器，只替换 HTTP 输出，避免重复启动监听线程。"""
    handler = object.__new__(service.CosyVoiceHandler)
    handler.path = "/health"
    handler.server = SimpleNamespace(synthesizer=synth, generation_gate=threading.Lock())
    responses = []
    handler._json = lambda status, body: responses.append((status, body))
    handler.do_GET()
    assert responses[0][0] == 200
    return responses[0][1]


@pytest.mark.parametrize("hidden_only", [False, True])
@pytest.mark.parametrize("model_streaming", [False, True])
def test_constructor_reports_selected_optimization_and_generation_mode(
    constructor_runtime, monkeypatch, hidden_only, model_streaming,
):
    state = constructor_runtime
    monkeypatch.setattr(state.optimizations, "install_qwen2_hidden_only", state.install)
    source, model = Path("synthetic-source"), Path("synthetic-model")
    synth = service.CosyVoiceSynthesizer(
        source, model, hidden_only=hidden_only, model_streaming=model_streaming,
    )
    assert state.validations == [(source, model)]
    assert state.model_arguments == (str(model), True)
    assert state.installations == ([state.encoder] if hidden_only else [])
    assert (synth.runtime_optimization is not None) is hidden_only
    info = constructor_health(synth)["runtime"]
    assert info["hidden_only"] is hidden_only
    assert info["model_streaming"] is model_streaming
    assert info["text_frontend"] == "wetext"
    assert info["optimization_reason"] == (
        "qwen2_unused_text_head_bypassed" if hidden_only else "disabled"
    )
    assert info["torch_threads"] == 16 and info["interop_threads"] == 24
    assert info["torch_version"] == "2.3.1+cu121"
    assert info["transformers_version"] == "4.51.3" and info["fp16"] is True
    assert state.warmups == [(service.WARMUP_TEXT, model_streaming, info)]


def test_constructor_defaults_enable_hidden_only_and_complete_segments(constructor_runtime, monkeypatch):
    state = constructor_runtime
    monkeypatch.setattr(state.optimizations, "install_qwen2_hidden_only", state.install)
    synth = service.CosyVoiceSynthesizer(Path("synthetic-source"), Path("synthetic-model"))
    info = constructor_health(synth)["runtime"]
    assert state.installations == [state.encoder]
    assert info["hidden_only"] is True and info["model_streaming"] is False


def test_constructor_installs_diagnostics_after_optimization_and_health_returns_fresh_counts(
    constructor_runtime, monkeypatch,
):
    state = constructor_runtime
    state.runtime.llm_job = lambda: "llm result"
    state.runtime.flow = SimpleNamespace(inference=lambda: "flow result")
    state.runtime.hift = SimpleNamespace(inference=lambda: "hift result")
    state.frontend.text_normalize = lambda text: text

    def install(encoder):
        assert not hasattr(state.runtime.llm_job, "__wrapped__")
        return state.install(encoder)

    monkeypatch.setattr(state.optimizations, "install_qwen2_hidden_only", install)
    synth = service.CosyVoiceSynthesizer(Path("synthetic-source"), Path("synthetic-model"))
    before = constructor_health(synth)["diagnostics"]
    assert set(before) == {"llm_job", "flow", "hift", "text_normalize"}
    assert all(record["calls"] == 0 for record in before.values())

    assert state.runtime.llm_job() == "llm result"
    assert state.runtime.flow.inference() == "flow result"
    assert state.runtime.hift.inference() == "hift result"
    assert state.frontend.text_normalize("synthetic input") == "synthetic input"
    after = constructor_health(synth)["diagnostics"]
    assert all(record["calls"] == 1 and record["wall_ms"] >= 0 for record in after.values())
    assert all(record["calls"] == 0 for record in before.values())
    assert "synthetic input" not in json.dumps(after)


@pytest.mark.parametrize("missing_encoder", [False, True])
def test_constructor_unknown_encoder_keeps_original_and_completes_warmup(
    constructor_runtime, monkeypatch, missing_encoder,
):
    state = constructor_runtime
    original = state.encoder.forward_one_step
    # 此处使用真实 guard；未知编码器和缺失嵌套属性都应拒绝优化，而非启动失败。
    monkeypatch.setitem(sys.modules, "cosyvoice.llm.llm", SimpleNamespace(Qwen2Encoder=type("KnownEncoder", (), {})))
    if missing_encoder:
        state.runtime.llm = SimpleNamespace()
    synth = service.CosyVoiceSynthesizer(Path("synthetic-source"), Path("synthetic-model"))
    assert state.encoder.forward_one_step is original
    assert state.encoder.forward_one_step() == "original"
    assert synth.runtime_optimization.applied is False
    info = constructor_health(synth)["runtime"]
    assert info["hidden_only"] is False
    assert info["optimization_reason"] == "unsupported_encoder_class"
    assert state.warmups == [(service.WARMUP_TEXT, False, info)]
