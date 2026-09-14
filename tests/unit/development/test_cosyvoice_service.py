"""使用合成器替身验证 CosyVoice 本机 HTTP 边界，不加载模型或 CUDA。"""

import argparse
import http.client
import importlib.util
import json
from pathlib import Path
import struct
import sys
import threading

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

    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, use_cache=True):
        self.calls.append((text, use_cache))
        return b"RIFF-cosyvoice-wave"

    def stream_chunks(self, text):
        self.calls.append((text, "stream"))
        yield b"RIFF-stream-one"
        yield b"RIFF-stream-two"


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
    assert synth.calls[-1] == ("分块测试", "stream")


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


def test_stream_uses_cached_reference_and_resets_hop_before_inference():
    calls = []

    class Model:
        model = type("Runtime", (), {"token_hop_len": 100})()

        def inference_zero_shot(self, *args, **kwargs):
            calls.append((args, kwargs, self.model.token_hop_len))
            yield {"tts_speech": object()}

    synth = object.__new__(service.CosyVoiceSynthesizer)
    synth._model = Model()
    synth._lock = threading.Lock()
    synth._prompt_wav = Path("fixed-reference.wav")
    synth.stream_token_hop_len = 25
    synth._wave_bytes = lambda _speech: b"RIFF-chunk"

    assert list(synth.stream_chunks("短句")) == [b"RIFF-chunk"]
    args, kwargs, hop_at_call = calls[0]
    assert args == ("短句", service.PROMPT_TEXT, synth._prompt_wav)
    assert kwargs == {
        "zero_shot_spk_id": service.REFERENCE_SPEAKER_ID,
        "stream": True,
    }
    assert hop_at_call == 25
