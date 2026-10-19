"""Xiaozhi 模型配置只读状态与显式连接检测；不返回私有 YAML 或密钥。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess

from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError


class XiaozhiModelProfiles:
    def __init__(self, project: Path, server: Path, profiles, *, model_settings_factory=None):
        self.project = Path(project).resolve()
        self.server = Path(server).resolve()
        self.profiles = profiles
        self.lock = asyncio.Lock()
        self.model_settings_factory = model_settings_factory

    def _inspect_one(self, profile: str) -> dict:
        python = self.server / ".venv/Scripts/python.exe"
        script = self.project / "scripts/development/xiaozhi/sync_model_config.py"
        if not python.is_file() or not script.is_file():
            raise ValueError("xiaozhi_model_config_unavailable")
        result = subprocess.run(
            [str(python), str(script), "--project", str(self.project),
             "--server", str(self.server), "--profile", profile, "--action", "check"],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode or not result.stdout or len(result.stdout) > 4096:
            raise ValueError("xiaozhi_model_config_unavailable")
        value = json.loads(result.stdout)
        # 白名单重建响应，即使外部脚本未来增加字段也不会意外把秘密传给网页。
        return {key: value.get(key) for key in (
            "profile", "config_matches", "provider_name", "configured_base_url",
            "configured_model", "transport",
        )}

    async def describe(self) -> dict:
        selected = self.profiles.selected("voice")
        try:
            inspected = await asyncio.to_thread(self._inspect_one, selected)
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {"enabled": False, "selected_profile": selected,
                    "status": "configuration_unavailable"}
        return {"enabled": True, "selected_profile": selected,
                "status": "configured" if inspected["config_matches"] else "restart_pending",
                **inspected}

    async def select(self, profile: str) -> dict:
        self.profiles.activate(profile, target="voice")
        return await self.describe()

    async def check(self) -> dict:
        """只发固定合成短句；不读取记忆、不重试，也不依赖当前网页模型。"""
        if self.lock.locked():
            raise ValueError("model_check_busy")
        async with self.lock:
            profile = self.profiles.selected("voice")
            checked_at = datetime.now(UTC).isoformat()
            try:
                settings = (self.model_settings_factory() if self.model_settings_factory is not None
                            else self.profiles.settings(profile))
                answer = await asyncio.to_thread(
                    OpenAICompatibleAnswerGenerator(settings).generate,
                    query="请只回复：连接正常", memory_context="",
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise AnswerGenerationError("invalid", code="model_response_invalid")
            except AnswerGenerationError as error:
                return {"state": "unavailable", "code": error.code,
                        "checked_at": checked_at, "profile": profile}
            except (ValueError, OSError):
                return {"state": "unavailable", "code": "model_configuration_invalid",
                        "checked_at": checked_at, "profile": profile}
            return {"state": "available", "code": None,
                    "checked_at": checked_at, "profile": profile}
