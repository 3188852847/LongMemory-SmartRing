"""启动面板状态读取只测合成文件，不枚举或控制真实进程。"""

from datetime import datetime, timedelta, timezone
import json

import pytest

from longmemory.entrypoints.api.launcher_status import read_launcher_status


def _snapshot(updated_at, instance="current"):
    return {
        "schema_version": 1,
        "launcher_instance": instance,
        "launcher_pid": 123,
        "updated_at": updated_at.isoformat(),
        "phase": "ready",
        "services": {"console": "ready", "voice": "running", "voxcpm2": "disabled",
                     "sanotts": "disabled"},
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


def test_v2_snapshot_exposes_only_bounded_startup_vad_choice(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot.update(schema_version=2, startup={"voice_enabled": True,
                                                "vad_profile": "close_talk"})
    path = tmp_path / "status.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = read_launcher_status(path, "current", now=now)

    assert result["startup"] == {"voice_enabled": True, "vad_profile": "close_talk"}


def test_v2_snapshot_rejects_unknown_vad_or_extra_startup_fields(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    path = tmp_path / "status.json"
    snapshot = _snapshot(now)
    snapshot.update(schema_version=2, startup={"voice_enabled": True,
                                                "vad_profile": "maximum"})
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert read_launcher_status(path, "current", now=now)["state"] == "launcher_unavailable"


def test_v3_snapshot_includes_tts_without_exposing_configuration(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot.update(schema_version=3, startup={"voice_enabled": True,
                                                "vad_profile": "noisy",
                                                "tts_backend": "sanotts"})
    path = tmp_path / "status.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    result = read_launcher_status(path, "current", now=now)
    assert result["startup"] == {"voice_enabled": True, "vad_profile": "noisy",
                                  "tts_backend": "sanotts"}
    snapshot["startup"] = {"voice_enabled": True, "vad_profile": "normal", "secret": "no"}
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert read_launcher_status(path, "current", now=now)["state"] == "launcher_unavailable"


def test_v4_snapshot_accepts_cosyvoice_without_changing_legacy_shape(tmp_path):
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot.update(
        schema_version=4,
        services=snapshot["services"] | {"cosyvoice3": "ready"},
        startup={"voice_enabled": True, "vad_profile": "normal",
                 "tts_backend": "cosyvoice3"},
    )
    path = tmp_path / "status.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    result = read_launcher_status(path, "current", now=now)

    assert result["services"]["cosyvoice3"] == "ready"
    assert result["startup"]["tts_backend"] == "cosyvoice3"


@pytest.mark.parametrize("voice,mode,vad,tts", [
    (True, "doubao_realtime", None, None),
    (True, "pipeline", "normal", "cosyvoice3"),
    (False, "doubao_realtime", None, None),
])
def test_v5_distinguishes_cloud_voice_from_local_tts(tmp_path, voice, mode, vad, tts):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot.update(schema_version=5,
                    services=snapshot["services"] | {"cosyvoice3": "disabled"},
                    startup={"voice_enabled": voice, "voice_mode": mode,
                             "vad_profile": vad, "tts_backend": tts})
    path = tmp_path / "status.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    result = read_launcher_status(path, "current", now=now)
    assert result["state"] == "ready"
    assert result["startup"] == snapshot["startup"]


@pytest.mark.parametrize("overrides", [
    {"voice_mode": "unknown"}, {"voice_enabled": "yes"},
    {"tts_backend": "cosyvoice3"}, {"vad_profile": "normal"}, {"api_key": "synthetic"},
])
def test_v5_rejects_misleading_or_unbounded_cloud_status(tmp_path, overrides):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = _snapshot(now)
    snapshot.update(schema_version=5,
                    services=snapshot["services"] | {"cosyvoice3": "disabled"},
                    startup={"voice_enabled": True, "voice_mode": "doubao_realtime",
                             "vad_profile": None, "tts_backend": None} | overrides)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert read_launcher_status(path, "current", now=now)["state"] == "launcher_unavailable"
