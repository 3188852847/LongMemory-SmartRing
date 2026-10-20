"""CPU 合成语料工具的边界测试；不在 pytest 中调用系统 TTS。"""

from array import array
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import wave

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("voice_turn_end_synthetic_ac_test", ROOT / "scripts/development/xiaozhi/voice_turn_end_synthetic.py")
synthetic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synthetic)


def pcm(values):
    result = array("h", values)
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def test_energy_trim_keeps_internal_silence_and_aligns_60ms():
    audio = pcm([0] * 960 + [2000] * 960 + [0] * 960 + [2000] * 400 + [0] * 960)
    result = synthetic.trim_to_active_frames(audio)
    assert len(result) == 3 * 1920
    assert result[1920:3840] == b"\x00" * 1920
    assert result[:1920] == pcm([2000] * 960)


def test_no_speech_cannot_be_labelled_as_synthetic_voice():
    with pytest.raises(ValueError, match="empty_speech"):
        synthetic.trim_to_active_frames(b"\x00" * 1920)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific generator")
def test_generator_creates_hash_bound_replay_manifest_without_audio_device(monkeypatch, tmp_path):
    monkeypatch.setattr(synthetic, "ROOT", tmp_path)
    def fake_speech(command, *, input, **kwargs):
        assert "SetOutputToWaveFile" in command[-1]
        assert "SetOutputToDefaultAudioDevice" not in command[-1]
        request = json.loads(input)
        for part in request["parts"]:
            with wave.open(part["path"], "wb") as sink:
                sink.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                sink.writeframes(pcm([0] * 960 + [1000] * 1920 + [0] * 960))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(synthetic.subprocess, "run", fake_speech)
    result = synthetic.generate()
    assert result["cases"] == 6
    assert result["pause_opportunities"] == 5
    assert not result["gpu_used"] and not result["audio_played"]
    sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
    try:
        from voice_turn_end_replay import load_public_manifest
        cases, _ = load_public_manifest(result["manifest"])
        assert len(cases) == 6
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific generator")
def test_generator_rejects_outside_or_existing_target_before_starting_speech(monkeypatch, tmp_path):
    monkeypatch.setattr(synthetic, "ROOT", tmp_path)
    target = tmp_path / "experiments/runs/existing"
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    for path in (tmp_path / "outside", target):
        with pytest.raises(ValueError, match="new_owned_directory"):
            synthetic.generate(path)
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific generator")
def test_generation_failure_retains_bounded_diagnostic_and_does_not_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(synthetic, "ROOT", tmp_path)
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr=b"diagnostic")
    monkeypatch.setattr(synthetic.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="voice_generation_failed"):
        synthetic.generate()
    assert len(calls) == 1
    findings = list((tmp_path / "experiments/runs").glob("*/generation-error.txt"))
    assert len(findings) == 1
    assert findings[0].read_bytes() == b"diagnostic"
