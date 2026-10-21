"""固定上游delete_audio_file=True回退分支的真实WAV/CPU Opus回归。"""
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
        pytest.skip("owner-installed CPU WAV/Opus environment unavailable")
    result = subprocess.run([str(PYTHON), "-I", "-B", "-X", "utf8",
        str(ROOT / "tests/fixtures/ad_full_wav_fallback_probe.py")],
        cwd=ROOT, capture_output=True, timeout=12,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-2500:]
    value = json.loads(result.stdout)
    print(json.dumps(value))
    return {row["case"]: row for row in value["cases"]}


def test_fixed_sdk_normal_fallback_reports_handoff(report):
    row = report["normal"]
    assert row["synthetic_full_wav_calls"] == 1
    assert row["packets_handed_off"] == 3 and row["decoded_samples"] == 4320
    assert row["delivery"]["handoff_started"]
    assert row["delivery"]["last_outcome"] == "fallback"


def test_fixed_sdk_callback_error_never_retries_already_queued_audio(report):
    row = report["callback_raises"]
    assert row["synthetic_full_wav_calls"] == row["packets_handed_off"] == 1
    assert row["delivery"]["handoff_started"]
    assert row["delivery"]["last_outcome"] == "failed"
    assert row["delivery"]["failure_code"] == "after_handoff"
    assert row["delivery"]["outcomes"]["fallback"] == row["delivery"]["outcomes"]["completed"] == 0


@pytest.mark.parametrize("case,packets", [("cancel_before_callback", 0), ("cancel_after_first", 1),
                                         ("cancel_after_first_raises", 1)])
def test_fixed_sdk_cancellation_drops_tail_without_retry(report, case, packets):
    row = report[case]
    assert row["synthetic_full_wav_calls"] == 1 and row["packets_handed_off"] == packets
    assert row["delivery"]["last_outcome"] == "cancelled"
    assert row["delivery"]["handoff_started"] is bool(packets)


@pytest.mark.parametrize("case", ["synthesis_returns_empty", "synthesis_raises", "invalid_wav"])
def test_fixed_sdk_pre_delivery_exhaustion_is_not_fallback_success(report, case):
    row = report[case]
    assert row["synthetic_full_wav_calls"] == 5 and row["packets_handed_off"] == 0
    assert not row["delivery"]["handoff_started"]
    assert row["delivery"]["last_outcome"] == "failed"
    assert row["delivery"]["failure_code"] == "before_handoff"
    assert row["delivery"]["outcomes"]["fallback"] == row["delivery"]["outcomes"]["completed"] == 0
