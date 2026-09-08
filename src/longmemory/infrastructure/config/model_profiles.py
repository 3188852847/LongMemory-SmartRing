"""本机模型配置档：密钥只写入被 Git 忽略的 env 文件，不经读取接口返回。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .settings import ModelSettings


PROFILE_FILES = {"campus": ".env", "official": ".env.deepseek.local"}
PROFILE_LABELS = {"campus": "学校模型", "official": "官方 DeepSeek"}
MANAGED_KEYS = (
    "LONGMEMORY_LLM_PROVIDER", "LONGMEMORY_LLM_BASE_URL",
    "LONGMEMORY_LLM_API_KEY", "LONGMEMORY_LLM_MODEL",
    "LONGMEMORY_LLM_TIMEOUT_SECONDS", "LONGMEMORY_LLM_MAX_TOKENS",
    "LONGMEMORY_LLM_ALLOW_HTTP",
)


class ModelProfileStore:
    """管理两个明确的本机配置档，并记录下次启动选择。"""

    def __init__(self, root: Path, *, current_profile: str = "campus"):
        self.root = root.resolve()
        self.selection_path = self.root / "data/control/model-profile.json"
        self.current_profile = self._profile(current_profile)

    @staticmethod
    def _profile(profile: str) -> str:
        if profile not in PROFILE_FILES:
            raise ValueError("unknown_model_profile")
        return profile

    def path(self, profile: str) -> Path:
        return self.root / PROFILE_FILES[self._profile(profile)]

    @staticmethod
    def _read_values(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return values
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in MANAGED_KEYS:
                values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _selection(self) -> dict:
        try:
            data = json.loads(self.selection_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def selected(self, target: str = "web") -> str:
        """返回网页或圆屏的下次启动档案，并兼容旧版 active_profile。"""
        if target not in {"web", "voice"}:
            raise ValueError("unknown_model_target")
        data = self._selection()
        web = data.get("web_profile", data.get("active_profile", "campus"))
        value = data.get("voice_profile", web) if target == "voice" else web
        try:
            return self._profile(value)
        except ValueError:
            return "campus"

    def describe(self) -> dict:
        selected = self.selected("web")
        return {
            "current_profile": self.current_profile,
            "next_start_profile": selected,
            "voice_next_start_profile": self.selected("voice"),
            "restart_required": self.current_profile != selected,
            "profiles": [self._describe_one(name) for name in PROFILE_FILES],
        }

    def _describe_one(self, profile: str) -> dict:
        values = self._read_values(self.path(profile))
        return {
            "id": profile, "label": PROFILE_LABELS[profile],
            "file_exists": self.path(profile).is_file(),
            "base_url": values.get("LONGMEMORY_LLM_BASE_URL", ""),
            "model": values.get("LONGMEMORY_LLM_MODEL", ""),
            "timeout_seconds": self._number(values.get("LONGMEMORY_LLM_TIMEOUT_SECONDS"), 30.0, float),
            "max_tokens": self._number(values.get("LONGMEMORY_LLM_MAX_TOKENS"), 512, int),
            "allow_http": values.get("LONGMEMORY_LLM_ALLOW_HTTP", "false").lower() == "true",
            "api_key_configured": bool(values.get("LONGMEMORY_LLM_API_KEY", "").strip()),
        }

    def settings(self, profile: str) -> ModelSettings:
        """供显式连接检测使用；调用者不得序列化或返回其中的 Key。"""
        values = self._read_values(self.path(self._profile(profile)))
        return ModelSettings(
            provider="openai_compatible",
            base_url=values.get("LONGMEMORY_LLM_BASE_URL", ""),
            api_key=values.get("LONGMEMORY_LLM_API_KEY", ""),
            model=values.get("LONGMEMORY_LLM_MODEL", ""),
            timeout_seconds=self._number(values.get("LONGMEMORY_LLM_TIMEOUT_SECONDS"), 30.0, float),
            max_tokens=self._number(values.get("LONGMEMORY_LLM_MAX_TOKENS"), 512, int),
            allow_http=values.get("LONGMEMORY_LLM_ALLOW_HTTP", "false").lower() == "true",
        )

    @staticmethod
    def _number(value, fallback, converter):
        try:
            return converter(value) if value is not None else fallback
        except (TypeError, ValueError):
            return fallback

    def save(self, profile: str, body: dict) -> dict:
        profile = self._profile(profile)
        required = {"base_url", "model", "timeout_seconds", "max_tokens", "allow_http", "activate"}
        allowed = required | {"api_key"}
        if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
            raise ValueError("invalid_model_profile")
        existing = self._read_values(self.path(profile))
        api_key = body.get("api_key") or existing.get("LONGMEMORY_LLM_API_KEY", "")
        if type(body["allow_http"]) is not bool or type(body["activate"]) is not bool:
            raise ValueError("invalid_model_profile")
        settings = ModelSettings(
            provider="openai_compatible", base_url=str(body["base_url"]).strip().rstrip("/"),
            api_key=str(api_key), model=str(body["model"]).strip(),
            timeout_seconds=float(body["timeout_seconds"]), max_tokens=int(body["max_tokens"]),
            allow_http=body["allow_http"],
        )
        values = {
            "LONGMEMORY_LLM_PROVIDER": settings.provider,
            "LONGMEMORY_LLM_BASE_URL": settings.base_url,
            "LONGMEMORY_LLM_API_KEY": settings.api_key,
            "LONGMEMORY_LLM_MODEL": settings.model,
            "LONGMEMORY_LLM_TIMEOUT_SECONDS": str(settings.timeout_seconds).removesuffix(".0"),
            "LONGMEMORY_LLM_MAX_TOKENS": str(settings.max_tokens),
            "LONGMEMORY_LLM_ALLOW_HTTP": str(settings.allow_http).lower(),
        }
        self._replace_managed_lines(self.path(profile), values)
        if body["activate"]:
            self.activate(profile, target="web")
        return self.describe()

    @staticmethod
    def _replace_managed_lines(path: Path, values: dict[str, str]) -> None:
        old = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        kept = [line for line in old if line.split("=", 1)[0].strip() not in MANAGED_KEYS]
        if kept and kept[-1].strip():
            kept.append("")
        kept.extend(f"{key}={values[key]}" for key in MANAGED_KEYS)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def activate(self, profile: str, *, target: str = "web") -> None:
        profile = self._profile(profile)
        if target not in {"web", "voice"}:
            raise ValueError("unknown_model_target")
        if not self.path(profile).is_file():
            raise ValueError("model_profile_not_configured")
        current = self._selection()
        web = current.get("web_profile", current.get("active_profile", "campus"))
        voice = current.get("voice_profile", web)
        if target == "web":
            web = profile
        else:
            voice = profile
        body = {"version": 2, "active_profile": web,
                "web_profile": web, "voice_profile": voice}
        self.selection_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.selection_path.with_name(f".{self.selection_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.selection_path)
        finally:
            temporary.unlink(missing_ok=True)
