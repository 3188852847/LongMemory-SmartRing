"""只读纯回声判据探针和已知成分误差定义，不加载应用或模型。"""

import ast
import importlib
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/"scripts/development/xiaozhi"))
    value = importlib.import_module("aec_echo_criterion_probe")
    assert Path(value.__file__).resolve() == ROOT/"scripts/development/xiaozhi/aec_echo_criterion_probe.py"
    return value


SOURCE = '''
def _apply_aec(self, ts, pcm):
    try:
        mic_audio = np.frombuffer(pcm,dtype=np.int16).astype(np.float32)
        best_ts,aligned_ref = ts,mic_audio.copy()
        best_corr,ref_rms,scale,coef = .99,700.,.5,3.
        output = mic_audio * .1
        if best_corr >= .97 and ref_rms > 500:
            output = output*.3
        output = np.clip(output,-32768,32767)
        return output.astype(np.int16).tobytes()
    except Exception:
        raise
'''


def test_probe_reads_actual_locals_and_preserves_output(module):
    _,base = module.load_helpers()
    source = ast.parse(SOURCE).body[0]
    original = base.compile_node(source,{"np":np})
    captured = []
    probe = base.compile_node(module.instrument(source),{"np":np,"_criterion":lambda *items:captured.append(items)})
    pcm = np.arange(-480,480,dtype=np.int16).tobytes()
    assert probe(None,321,pcm) == original(None,321,pcm)
    assert len(captured) == 1 and captured[0][0] == 321
    assert captured[0][2:6] == (.99,700.,.5,3.)
    assert captured[0][1].astype(np.int16).tobytes() == pcm


def test_unknown_algorithm_shape_rejected(module):
    with pytest.raises(ValueError,match="unexpected_aec_clip_shape"):
        module.instrument(ast.parse('def f():\n    try:\n        return b""\n    except Exception:\n        raise').body[0])


def test_fixed_path_has_exact_delay_and_taps(module):
    far = np.zeros(97920,dtype=np.int16)
    far[0] = 10000
    output = np.frombuffer(module.path_echo(far.tobytes(),np),dtype=np.int16)
    assert len(output) == 96000
    assert np.flatnonzero(output).tolist() == [160,161]
    assert output[[160,161]].tolist() == [4400,1100]


def test_known_near_error_and_echo_residue_are_different_quantities(module):
    near = np.full(960,1000,dtype=np.int16).tobytes()
    mix = np.full(960,2000,dtype=np.int16).tobytes()
    ideal = module.waveform_metrics(near,mix,near,True,True,np)
    assert ideal["error_energy_over_near_energy"] == 0
    raw = module.waveform_metrics(mix,mix,near,True,True,np)
    assert raw["error_energy_over_near_energy"] == 1
    echo = module.waveform_metrics(near,mix,near,False,True,np)
    assert echo["echo_only_residual_energy_ratio"] == .25
    assert "echo_only_residual_energy_ratio" not in raw
    assert "error_energy_over_near_energy" not in echo


def test_metrics_refuse_mismatched_shapes(module):
    with pytest.raises(ValueError,match="metric_shape_mismatch"):
        module.waveform_metrics(bytes(2),bytes(4),bytes(4),False,True,np)


def test_excess_wall_budget_rejected_before_any_io(module,tmp_path):
    out = tmp_path/'not-created'
    with pytest.raises(SystemExit):
        module.main(['--output',str(out),'--baseline-run','not-read','--model','not-loaded','--max-seconds','121'])
    assert not out.exists()
