"""遗留语音清理的离线协议测试；不查询或停止真实进程。"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/launcher"
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location(
        "voice_recovery_tested", DIRECTORY / "voice_recovery.py"
    )
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
finally:
    sys.path.pop(0)


def response(value, returncode=0):
    import json
    return SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps(value).encode("utf-8"),
    )


def test_cleanup_script_requires_all_three_ports_before_stopping(monkeypatch):
    captured = []
    monkeypatch.setattr(
        recovery, "run_ps",
        lambda source: captured.append(source) or response({"state": "stopped", "process_id": 321}),
    )
    assert recovery.close_stale_voice("192.168.124.111") == {
        "state": "stopped", "process_id": 321,
    }
    script = captured[0]
    assert all(str(port) in script for port in (8000, 8003, 8766))
    assert script.index("voice_port_ownership_mismatch") < script.index("Stop-Process")
    assert "pythonw" in script and "ADDRESS" not in script


@pytest.mark.parametrize("value", [
    {"state": "free"},
    {"state": "refused", "reason": "voice_port_ownership_mismatch"},
    {"state": "failed", "reason": "inspection_or_stop_failed"},
])
def test_non_stopped_results_never_invent_a_pid(monkeypatch, value):
    monkeypatch.setattr(recovery, "run_ps", lambda _source: response(value))
    assert recovery.close_stale_voice("192.168.1.9") == value


@pytest.mark.parametrize("value", [
    {"state": "stopped"},
    {"state": "stopped", "process_id": "321"},
    {"state": "unknown"},
    {"state": "free", "private": "must-not-escape"},
    {"state": "refused", "reason": "untrusted-detail"},
])
def test_malformed_result_is_not_reported_as_success(monkeypatch, value):
    monkeypatch.setattr(recovery, "run_ps", lambda _source: response(value))
    with pytest.raises(ValueError):
        recovery.close_stale_voice("192.168.1.9")


def test_public_or_invalid_address_is_rejected_before_powershell(monkeypatch):
    called = []
    monkeypatch.setattr(recovery, "run_ps", lambda _source: called.append(True))
    with pytest.raises(ValueError):
        recovery.close_stale_voice("8.8.8.8")
    assert not called
