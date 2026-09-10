"""只用合成器替身验证本机 HTTP 契约，不加载模型或 CUDA。"""

import argparse
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "scripts/development/voxcpm"
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location("voxcpm_service_test", DIRECTORY / "service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
sys.path.pop(0)


class FakeSynthesizer:
    def __init__(self):
        self.texts = []

    def synthesize(self, text):
        self.texts.append(text)
        return b"RIFF-synthetic-wave"


@pytest.fixture
def local_service():
    synth = FakeSynthesizer()
    server = service.VoxCPMHTTPServer(("127.0.0.1", 0), synth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], synth
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    payload = None if body is None else json.dumps(body).encode()
    final_headers = dict(headers or {})
    if payload is not None:
        final_headers.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=payload, headers=final_headers)
    response = conn.getresponse(); data = response.read(); conn.close()
    return response.status, response.getheader("Content-Type"), data


def test_health_and_xiaozhi_custom_tts_contract(local_service):
    port, synth = local_service
    status, _, body = request(port, "GET", "/health")
    assert status == 200 and json.loads(body)["provider"] == "voxcpm2"
    status, content_type, body = request(port, "POST", "/v1/audio/speech", {
        "input": "  合成测试  ", "response_format": "wav", "stream": False,
        "voice": "ignored-upstream-field", "speed": 1,
    })
    assert status == 200 and content_type == "audio/wav"
    assert body == b"RIFF-synthetic-wave" and synth.texts == ["合成测试"]


@pytest.mark.parametrize("body", [
    {}, {"input": ""}, {"input": "x" * 601},
    {"input": "ok", "response_format": "mp3"}, {"input": "ok", "stream": True},
])
def test_rejects_invalid_generation_requests(local_service, body):
    status, _, _ = request(local_service[0], "POST", "/v1/audio/speech", body)
    assert status == 400


def test_rejects_browser_origin_and_non_loopback_binding(local_service):
    status, _, _ = request(local_service[0], "POST", "/v1/audio/speech", {"input": "ok"},
                           {"Origin": "https://example.invalid"})
    assert status == 403
    with pytest.raises(argparse.ArgumentTypeError):
        service.loopback_address("192.168.1.2")


def test_invalid_profile_falls_back_without_exposing_arbitrary_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"version":1,"reference":"../../secret.wav","style":"",
                                "cfg_value":2.0,"quality":"balanced"}), encoding="utf-8")
    monkeypatch.setattr(service, "PROFILE_PATH", path)
    assert service.current_profile() == {"version":1,"reference":None,"style":"",
                                         "cfg_value":2.0,"quality":"balanced"}


def test_waveform_quality_rejects_long_near_silence_and_accepts_speech_like_audio():
    silent = [0.00001] * 48000
    voiced = [0.0, 0.08, -0.06, 0.04] * 12000

    assert service.waveform_quality(silent, 48000)["acceptable"] is False
    result = service.waveform_quality(voiced, 48000)
    assert result["acceptable"] is True
    assert result["duration_seconds"] == 1.0


def test_voxcpm_retries_silent_result_with_a_different_seed(monkeypatch):
    class FakeWaveform(list):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            return FakeWaveform(value) if isinstance(key, slice) else value

    class FakeModel:
        def __init__(self):
            self.results = [FakeWaveform([0.00001] * 4800), FakeWaveform([0.1, -0.1] * 2400)]
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return self.results.pop(0)

    class FakeCuda:
        def __init__(self):
            self.seeds = []

        def manual_seed_all(self, seed):
            self.seeds.append(seed)

    class FakeTorch:
        def __init__(self):
            self.seeds = []
            self.cuda = FakeCuda()

        def manual_seed(self, seed):
            self.seeds.append(seed)

    class FakeSoundfile:
        @staticmethod
        def write(output, _waveform, _rate, **_kwargs):
            output.write(b"RIFF-retried-wave")

    monkeypatch.setattr(service, "current_profile", lambda: {
        "version": 1, "reference": None, "style": "", "cfg_value": 2.0,
        "quality": "balanced",
    })
    synth = service.VoxCPMSynthesizer.__new__(service.VoxCPMSynthesizer)
    synth._torch = FakeTorch()
    synth._soundfile = FakeSoundfile()
    synth._model = FakeModel()
    synth._sample_rate = 48000
    synth._cache_entries = 4
    synth._cache = service.OrderedDict()
    synth._lock = threading.Lock()

    assert synth.synthesize("测试") == b"RIFF-retried-wave"
    assert synth._torch.seeds == [42, 43]
    assert synth._torch.cuda.seeds == [42, 43]
    assert [call["max_len"] for call in synth._model.calls] == [service.MAX_AUDIO_TOKENS] * 2
