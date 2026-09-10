"""启动面板的非敏感本地首选项；不保存密钥和删除权限。"""

import json
import os
from pathlib import Path


PREFERENCES_VERSION = 2
RISK_ACK_VERSION = "campus-http-v1"
# 只影响当前本机启动面板，不写入偏好文件，也不改变服务端安全默认。
DEFAULT_SESSION_ALLOW_MEMORY_DELETE = True

DEFAULTS = {
    "voice": False,
    "start_page": "chat",
    "database": "",
    "voice_root": "",
    "lan_ip": "",
    "role": "elysia_v1",
    "memory_extraction": "rules",
    "memory_retrieval": "keyword",
    "memory_consolidation": False,
    "embedding_model_dir": "",
    "tts_backend": "edge",
    "vad_profile": "normal",
    "http_risk_ack": False,
}

_CHOICES = {
    "start_page": {"overview", "chat", "device", "memories", "settings"},
    "role": {"elysia_v1", "plain_v1"},
    "memory_extraction": {"rules", "llm"},
    "memory_retrieval": {"keyword", "hybrid"},
    "tts_backend": {"edge", "voxcpm2"},
    "vad_profile": {"normal", "noisy", "close_talk"},
}
_PATH_FIELDS = {"database", "voice_root", "embedding_model_dir"}


def load_preferences(path: Path) -> dict:
    """损坏或未知字段只回退默认值，不让启动面板因偏好文件无法打开。"""

    result = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return result
    if not isinstance(raw, dict):
        return result
    if isinstance(raw.get("voice"), bool):
        result["voice"] = raw["voice"]
    if isinstance(raw.get("memory_consolidation"), bool):
        result["memory_consolidation"] = raw["memory_consolidation"]
    for field, allowed in _CHOICES.items():
        if raw.get(field) in allowed:
            result[field] = raw[field]
    for field in _PATH_FIELDS:
        value = raw.get(field)
        if isinstance(value, str) and len(value) <= 2048:
            result[field] = value
    lan_ip = raw.get("lan_ip")
    if isinstance(lan_ip, str) and len(lan_ip) <= 64:
        result["lan_ip"] = lan_ip
    result["http_risk_ack"] = raw.get("http_risk_ack_version") == RISK_ACK_VERSION
    return result


def save_preferences(path: Path, values: dict) -> None:
    """白名单序列化并原子替换；显式排除 allow_memory_delete。"""

    body = {
        "version": PREFERENCES_VERSION,
        "voice": bool(values.get("voice", False)),
        "start_page": values.get("start_page", DEFAULTS["start_page"]),
        "database": str(values.get("database", ""))[:2048],
        "voice_root": str(values.get("voice_root", ""))[:2048],
        "lan_ip": str(values.get("lan_ip", ""))[:64],
        "role": values.get("role", DEFAULTS["role"]),
        "memory_extraction": values.get(
            "memory_extraction", DEFAULTS["memory_extraction"]
        ),
        "memory_retrieval": values.get(
            "memory_retrieval", DEFAULTS["memory_retrieval"]
        ),
        "memory_consolidation": bool(values.get("memory_consolidation", False)),
        "embedding_model_dir": str(values.get("embedding_model_dir", ""))[:2048],
        "tts_backend": values.get("tts_backend", DEFAULTS["tts_backend"]),
        "vad_profile": values.get("vad_profile", DEFAULTS["vad_profile"]),
        "http_risk_ack_version": (
            RISK_ACK_VERSION if values.get("http_risk_ack") else None
        ),
    }
    for field, allowed in _CHOICES.items():
        if body[field] not in allowed:
            raise ValueError(f"launcher_preference_{field}_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_model_profile(path: Path, target: str = "web") -> str:
    """读取跨启动器与网页共享的非敏感配置档指针。"""
    if target not in {"web", "voice"}:
        raise ValueError("launcher_model_target_invalid")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        web = data.get("web_profile", data.get("active_profile"))
        value = data.get("voice_profile", web) if target == "voice" else web
    except (OSError, ValueError, TypeError):
        value = None
    return value if value in {"campus", "official"} else "campus"


def save_model_profile(path: Path, profile: str, target: str = "web") -> None:
    if profile not in {"campus", "official"}:
        raise ValueError("launcher_model_profile_invalid")
    if target not in {"web", "voice"}:
        raise ValueError("launcher_model_target_invalid")
    web = load_model_profile(path, "web")
    voice = load_model_profile(path, "voice")
    if target == "web":
        web = profile
    else:
        voice = profile
    body = {"version": 2, "active_profile": web,
            "web_profile": web, "voice_profile": voice}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_memory_backend(path: Path) -> str:
    """读取圆屏下次启动的记忆后端；损坏文件安全回退 LongMemory。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("selected_backend") if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        value = None
    return value if value in {"longmemory", "xiaozhi_local", "none"} else "longmemory"


def save_memory_backend(path: Path, backend: str) -> None:
    if backend not in {"longmemory", "xiaozhi_local", "none"}:
        raise ValueError("launcher_memory_backend_invalid")
    body = {"version": 1, "selected_backend": backend}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
