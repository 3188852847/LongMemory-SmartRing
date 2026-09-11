"""小智 VAD 档位窄接口。

实际 YAML 解析和修改由小智自己的 Python 环境执行；本层只允许三个
固定档位，不向浏览器暴露私有配置、密钥或子进程输出。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess

from aiohttp import web


PROFILES = {"normal", "noisy", "close_talk"}
VALUE_KEYS = {"threshold", "threshold_low", "min_silence_duration_ms"}


def _public_status(value):
    """把子进程结果投影为固定公开字段，即使脚本未来增加字段也不会泄露。"""
    if not isinstance(value, dict) or value.get("profile") not in PROFILES | {"custom"}:
        raise ValueError("vad_operation_failed")
    values = value.get("values")
    digest = value.get("digest")
    if (
        not isinstance(values, dict)
        or set(values) != VALUE_KEYS
        or type(values["threshold"]) not in {int, float}
        or type(values["threshold_low"]) not in {int, float}
        or type(values["min_silence_duration_ms"]) is not int
        or not 0 <= values["threshold_low"] <= values["threshold"] <= 1
        or not 100 <= values["min_silence_duration_ms"] <= 5000
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("vad_operation_failed")
    return {
        "profile": value["profile"],
        "values": values,
        "digest": digest,
        "runtime": "unverified",
    }


class VadSettings:
    def __init__(self, server: Path, project: Path):
        self.server = Path(server).resolve()
        self.project = Path(project).resolve()
        self.lock = asyncio.Lock()

    async def call(self, body: dict):
        if self.lock.locked():
            raise ValueError("busy")
        async with self.lock:
            python = self.server / ".venv/Scripts/python.exe"
            script = self.project / "scripts/development/xiaozhi/sync_vad_config.py"
            if not python.is_file() or not script.is_file():
                raise ValueError("unavailable")
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    [str(python), str(script), str(self.server)],
                    input=json.dumps(body).encode(),
                    capture_output=True,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError("vad_operation_unverified") from None
            if result.returncode or not result.stdout or len(result.stdout) > 4096:
                raise ValueError("vad_operation_failed")
            try:
                value = json.loads(result.stdout)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ValueError("vad_operation_failed") from None
            return _public_status(value)


def register_vad_routes(app, backend):
    async def settings(request):
        if backend is None:
            return web.json_response({"error": "vad_not_enabled"}, status=403)
        try:
            if request.method == "GET":
                return web.json_response(await backend.call({"action": "status"}))
            body = await request.json()
            if (
                not isinstance(body, dict)
                or set(body) != {"profile", "expected_digest"}
                or body.get("profile") not in PROFILES
                or not isinstance(body.get("expected_digest"), str)
                or len(body["expected_digest"]) != 64
            ):
                raise ValueError("invalid_body")
            return web.json_response(await backend.call({"action": "apply", **body}))
        except (ValueError, OSError, TypeError, json.JSONDecodeError):
            return web.json_response({"error": "vad_operation_failed_recheck"}, status=409)

    app.router.add_get("/api/vad-settings", settings, allow_head=False)
    app.router.add_put("/api/vad-settings", settings)
