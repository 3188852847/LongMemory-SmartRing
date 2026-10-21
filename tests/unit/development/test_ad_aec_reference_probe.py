"""固定服务端AEC的合成性质记录；不是声学/VAD/近端识别验收。"""
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
PYTHON = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe"


@pytest.fixture(scope="module")
def report():
    if not PYTHON.is_file():
        pytest.skip("owner-installed CPU numpy/Opus runtime unavailable")
    result = subprocess.run([str(PYTHON), "-I", "-B", "-X", "utf8",
        str(ROOT / "tests/fixtures/ad_aec_reference_probe.py")], capture_output=True,
        cwd=ROOT, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-2000:]
    value = json.loads(result.stdout)
    print(json.dumps(value))
    return value


def by_case(report, name):
    return next(row for row in report["scenarios"] if row["case"] == name)


def test_missing_or_single_reference_bypasses_without_changing_pcm(report):
    assert by_case(report, "no_reference")["output_equals_input"]
    assert by_case(report, "one_reference")["output_equals_input"]


def test_expected_echo_suppression_does_not_prove_double_talk_safety(report):
    assert by_case(report, "echo_only")["rms_ratio"] < .1
    assert by_case(report, "near_only_quadrature")["rms_ratio"] < .1
    assert report["quadrature_time_domain_dot"] == 0
    assert not report["asr_vad_models_executed"]


def test_nonoverlap_near_component_is_also_windowed(report):
    row = by_case(report, "near_only_disjoint_spectrum")
    assert .5 < row["rms_ratio"] < .7
    mixed = by_case(report, "echo_plus_near")
    assert 0 < mixed["near_700hz_projection_after"] < mixed["near_700hz_projection_before"]


def test_raw_reference_age_is_not_a_rejection_gate_in_pinned_algorithm(report):
    assert by_case(report, "stale_reference_quadrature")["nearest_raw_timestamp_delta_ms"] == 60000
    assert report["stale_and_current_outputs_identical"]
    assert report["aec_warnings"] == 0


def test_reference_decodes_to_same_pcm_format_from_both_opus_encoding_rates(report):
    assert report["codec_formats"] == [dict(encoded_rate=rate, encoded_frames=1,
        reference_decode_rate=16000, reference_pcm_bytes=1920) for rate in (16000, 24000)]
    assert report["format"] == "PCM16LE_16k_mono_60ms"
    assert not report["torch_imported"] and not report["network_used"] and not report["audio_files_written"]
