"""读取启动器的最小运行快照；不探测、启动或停止任何外部进程。"""

from datetime import datetime, timezone
import json
from pathlib import Path


ALLOWED_PHASES = {"starting", "ready", "stopping", "stopped", "failed"}
ALLOWED_SERVICES = {"console", "voice", "voxcpm2", "sanotts", "cosyvoice3"}
LEGACY_SERVICES = {"console", "voice", "voxcpm2", "sanotts"}
ALLOWED_STATES = {"disabled", "running", "ready", "exited"}
ALLOWED_VAD_PROFILES = {"normal", "noisy", "close_talk"}
ALLOWED_TTS_BACKENDS = {"edge", "voxcpm2", "sanotts", "cosyvoice3"}


def read_launcher_status(path: Path | None, expected_instance: str | None, *, now=None,
                         maximum_age_seconds: float = 5.0) -> dict:
    """只接受当前控制台实例的新鲜快照，旧启动器文件永远不会显示为正常。"""
    unavailable = {
        "enabled": False,
        "state": "launcher_unavailable",
        "reason": "manual_start_or_status_unavailable",
        "services": {},
    }
    if path is None or not expected_instance:
        return unavailable
    try:
        if path.stat().st_size > 32_768:
            return unavailable
        raw = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(raw["updated_at"])
        if updated.tzinfo is None:
            return unavailable
        services = raw["services"]
        schema_version = raw.get("schema_version")
        startup = raw.get("startup", {})
        if (
            schema_version not in {1, 2, 3, 4}
            or raw.get("launcher_instance") != expected_instance
            or raw.get("phase") not in ALLOWED_PHASES
            or not isinstance(services, dict)
            or set(services) != (
                ALLOWED_SERVICES if schema_version == 4 else LEGACY_SERVICES
            )
            or any(value not in ALLOWED_STATES for value in services.values())
            or not isinstance(startup, dict)
            or (schema_version == 2 and set(startup) != {"voice_enabled", "vad_profile"})
            or (schema_version in {3, 4} and set(startup) != {"voice_enabled", "vad_profile", "tts_backend"})
            or (schema_version == 2 and type(startup.get("voice_enabled")) is not bool)
            or (schema_version in {3, 4} and type(startup.get("voice_enabled")) is not bool)
            or (schema_version == 2 and startup.get("vad_profile") not in
                (ALLOWED_VAD_PROFILES if startup.get("voice_enabled") else {None}))
            or (schema_version in {3, 4} and startup.get("vad_profile") not in
                (ALLOWED_VAD_PROFILES if startup.get("voice_enabled") else {None}))
            or (schema_version in {3, 4} and startup.get("tts_backend") not in
                (ALLOWED_TTS_BACKENDS if startup.get("voice_enabled") else {None}))
        ):
            return unavailable
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return unavailable
    current = now or datetime.now(timezone.utc)
    age = max(0.0, (current - updated.astimezone(timezone.utc)).total_seconds())
    if age > maximum_age_seconds:
        return {
            "enabled": True,
            "state": "stale",
            "reason": "launcher_status_stale",
            "updated_at": raw["updated_at"],
            "age_seconds": round(age, 1),
            "services": {},
        }
    return {
        "enabled": True,
        "state": raw["phase"],
        "reason": None,
        "updated_at": raw["updated_at"],
        "age_seconds": round(age, 1),
        "services": services,
        "startup": startup if schema_version in {2, 3, 4} else {},
    }
