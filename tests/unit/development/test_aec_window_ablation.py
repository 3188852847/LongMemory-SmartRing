"""窗函数四臂的纯合成恒等/频率/配对边界；不加载模型或读取日用。"""

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
import wave

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/development/xiaozhi"))
    value = importlib.import_module("aec_window_ablation")
    assert Path(value.__file__).resolve() == ROOT / "scripts/development/xiaozhi/aec_window_ablation.py"
    return value


SOURCE = '''
def _apply_aec(self, timestamp, pcm_frame):
    try:
        mic_audio = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32)
        n = len(mic_audio)
        mic_fft = np.fft.rfft(mic_audio * np.hanning(n))
        best_ts = timestamp
        aligned_ref = np.frombuffer(self.ref, dtype=np.int16).astype(np.float32)[:n]
        if len(aligned_ref) < n:
            aligned_ref = np.pad(aligned_ref, (0,n-len(aligned_ref)))
        mic_mag = np.abs(mic_fft)
        mic_phase = np.angle(mic_fft)
        result_mag = np.maximum(mic_mag * self.gain, mic_mag * .1)
        result_fft = result_mag * np.exp(1j * mic_phase)
        output = np.fft.irfft(result_fft,n)
        best_corr, ref_rms = self.corr, 700.
        if best_corr >= .97 and ref_rms > 500:
            output = output * .3
        return np.clip(output,-32768,32767).astype(np.int16).tobytes()
    except Exception:
        raise
'''


def arms(module, connection, pcm):
    base = module.load_base()
    result, references = {}, {}
    node = ast.parse(SOURCE).body[0]
    for arm in module.ARMS:
        selected = []
        function = base.compile_node(module.variant(node, arm, base), {"np": np,
            "_selected_reference": lambda ts, ref: selected.append((ts, ref.astype(np.int16).tobytes()))})
        result[arm] = function(connection, 123, pcm)
        references[arm] = selected
    assert all(value == references["original"] for value in references.values())
    return result


def test_window_only_is_hann_not_identity_and_omits_extra_point_three(module):
    raw = np.full(960, 1000, np.int16)
    conn = SimpleNamespace(ref=raw.tobytes(), gain=.5, corr=1.)
    result = arms(module, conn, raw.tobytes())
    assert result["identity"] == raw.tobytes()
    expected = (raw.astype(float) * np.hanning(960)).astype(np.int16)
    actual = np.frombuffer(result["hann_only"], np.int16)
    assert np.max(abs(actual.astype(np.int32) - expected)) <= 1
    assert actual[0] == actual[-1] == 0 and actual.max() > 990
    candidate = np.frombuffer(result["raw_frame_spectral_gain"], np.int16)
    assert np.max(abs(candidate.astype(np.int32) - 150)) <= 1  # .5频率增益与.3仍在，无逐包Hann包络。
    assert all(type(value) is bytes and len(value) == 1920 for value in result.values())


def test_candidate_is_frequency_selective_not_overall_amplification(module):
    t = np.arange(960) / 16000
    raw = np.rint(2000 * np.sin(2*np.pi*400*t) + 2000 * np.sin(2*np.pi*2000*t)).astype(np.int16)
    frequencies = np.fft.rfftfreq(960,1/16000)
    conn = SimpleNamespace(ref=raw.tobytes(), gain=np.where(frequencies < 1000,.5,.1), corr=0.)
    result = arms(module, conn, raw.tobytes())
    output = np.frombuffer(result["raw_frame_spectral_gain"], np.int16).astype(float)
    amplitudes = [2 * np.dot(output,np.sin(2*np.pi*freq*t))/960 for freq in (400,2000)]
    assert amplitudes[0] == pytest.approx(1000, abs=2)
    assert amplitudes[1] == pytest.approx(200, abs=2)
    assert np.sqrt(np.mean(output**2)) <= np.sqrt(np.mean(raw.astype(float)**2))


def test_zero_spectrum_candidate_stays_finite(module):
    raw = bytes(1920)
    result = arms(module, SimpleNamespace(ref=raw,gain=.5,corr=0.), raw)
    assert all(value == raw for value in result.values())


def test_unknown_arm_is_rejected(module):
    with pytest.raises(ValueError,match="unknown_ablation_arm"):
        module.variant(ast.parse(SOURCE).body[0], "global_boost", module.load_base())


@pytest.mark.parametrize("rate,frames", [(24000,960),(16000,160001)])
def test_input_format_or_duration_change_is_rejected(module,tmp_path,rate,frames):
    path=tmp_path/'input.wav'
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames*2))
    with pytest.raises(ValueError):
        module.read_pcm(path)


def test_over_wall_budget_rejected_before_directory_creation(module,tmp_path):
    output=tmp_path/'not-created'
    with pytest.raises(SystemExit):
        module.main(['--output',str(output),'--baseline-run','not-read','--model','not-loaded','--max-seconds','121'])
    assert not output.exists()
