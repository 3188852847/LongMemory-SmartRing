"""启动面板状态读取只测合成文件，不枚举或控制真实进程。"""

from datetime import datetime, timedelta, timezone
import json

from longmemory.entrypoints.api.launcher_status import read_launcher_status


def _snapshot(updated_at, instance="current"):
    return {
        "schema_version": 1,
        "launcher_instance": instance,
        "launcher_pid": 123,
        "updated_at": updated_at.isoformat(),
        "phase": "ready",
        "services": {"console": "ready", "voice": "running", "voxcpm2": "disabled"},
    }


def test_current_matching_snapshot_is_returned(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_snapshot(now)), encoding="utf-8")

    result = read_launcher_status(path, "current", now=now + timedelta(seconds=1))

    assert result["enabled"] is True
    assert result["state"] == "ready"
    assert result["age_seconds"] == 1.0
    assert result["services"]["console"] == "ready"


def test_old_instance_corrupt_and_missing_snapshots_never_look_ready(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_snapshot(now, instance="old")), encoding="utf-8")
    assert read_launcher_status(path, "current", now=now)["state"] == "launcher_unavailable"
    path.write_text("{broken", encoding="utf-8")
    assert read_launcher_status(path, "current", now=now)["state"] == "launcher_unavailable"
    assert read_launcher_status(tmp_path / "missing.json", "current", now=now)["state"] == "launcher_unavailable"


def test_stale_snapshot_hides_service_states(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_snapshot(now - timedelta(seconds=6))), encoding="utf-8")

    result = read_launcher_status(path, "current", now=now)

    assert result["state"] == "stale"
    assert result["services"] == {}
