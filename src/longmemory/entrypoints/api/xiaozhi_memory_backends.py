"""圆屏记忆后端的磁盘状态；选择只在下次统一启动时应用。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess


class XiaozhiMemoryBackends:
    def __init__(self, project: Path, server: Path, store):
        self.project = Path(project).resolve()
        self.server = Path(server).resolve()
        self.store = store

    def _inspect(self, backend: str) -> dict:
        python = self.server / ".venv/Scripts/python.exe"
        script = self.project / "scripts/development/xiaozhi/sync_memory_config.py"
        if not python.is_file() or not script.is_file():
            raise ValueError("xiaozhi_memory_config_unavailable")
        result = subprocess.run(
            [str(python), str(script), "--server", str(self.server),
             "--profile", backend, "--action", "check"],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode or not result.stdout or len(result.stdout) > 4096:
            raise ValueError("xiaozhi_memory_config_unavailable")
        value = json.loads(result.stdout)
        return {key: value.get(key) for key in (
            "profile", "config_matches", "provider_name", "configured_provider"
        )}

    async def describe(self) -> dict:
        selected = self.store.selected()
        try:
            inspected = await asyncio.to_thread(self._inspect, selected)
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {"enabled": False, "selected_backend": selected,
                    "status": "configuration_unavailable"}
        return {
            "enabled": True,
            "selected_backend": selected,
            "status": "configured" if inspected["config_matches"] else "restart_pending",
            **inspected,
        }

    async def select(self, backend: str) -> dict:
        self.store.select(backend)
        return await self.describe()
