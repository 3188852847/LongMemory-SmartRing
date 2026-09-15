"""独立配置入口：只读取指定 dotenv 文件，不展开变量、不修改进程环境。

3.0 与旧版的协议、鉴权不同。固定已核实的官方地址和模型，防止把
凭据意外发到可编辑地址；本模块只用标准库，启动器可离线检查配置。
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / ".env.doubao.local"
OFFICIAL_URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
MODEL = "1.2.6.1"
DEFAULT_SPEAKER = "zh_female_vv_jupiter_bigtts"
DEFAULT_INSTRUCTIONS = "你是一位友善的中文语音助手。请自然、简洁地回答。"
ALLOWED_KEYS = frozenset({
    "DOUBAO_API_KEY", "DOUBAO_SPEAKER", "DOUBAO_INSTRUCTIONS",
    "DOUBAO_MODEL", "DOUBAO_WS_URL",
})


class ConfigError(ValueError):
    """只包含固定提示与字段名，不含原始配置值或文件内容。"""


def _value(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f"配置字段格式无效：{name}")
    # dotenv 不执行 shell，但拒绝常见展开形式，避免用户误以为展开已生效。
    if "${" in value or "$(" in value or "`" in value:
        raise ConfigError(f"配置字段不允许变量或命令展开：{name}")
    if not allow_empty and not value.strip():
        raise ConfigError(f"缺少配置字段：{name}")
    return value.strip()


@dataclass(frozen=True)
class DoubaoConfig:
    api_key: str = field(repr=False)
    speaker: str = DEFAULT_SPEAKER
    instructions: str = field(default=DEFAULT_INSTRUCTIONS, repr=False)
    model: str = MODEL
    url: str = OFFICIAL_URL

    @property
    def output_sample_rate(self) -> int:
        return 24000

    @property
    def input_sample_rate(self) -> int:
        return 16000

    def __post_init__(self):
        for attr, key in (("api_key", "DOUBAO_API_KEY"), ("speaker", "DOUBAO_SPEAKER"),
                          ("instructions", "DOUBAO_INSTRUCTIONS"),
                          ("model", "DOUBAO_MODEL"), ("url", "DOUBAO_WS_URL")):
            normalized = _value(getattr(self, attr), key)
            object.__setattr__(self, attr, normalized)
        if len(self.api_key) > 4096 or any(c.isspace() for c in self.api_key):
            raise ConfigError("配置字段格式无效：DOUBAO_API_KEY")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", self.speaker):
            raise ConfigError("配置字段格式无效：DOUBAO_SPEAKER")
        if len(self.instructions) > 8000:
            raise ConfigError("配置字段过长：DOUBAO_INSTRUCTIONS")
        if self.url != OFFICIAL_URL:
            raise ConfigError("DOUBAO_WS_URL 必须使用已支持的官方 3.0 地址")
        if self.model != MODEL:
            raise ConfigError("DOUBAO_MODEL 必须使用已支持的 3.0 模型")


def _read_values(path: Path, *, missing_ok: bool = False) -> dict[str, str]:
    try:
        if path.stat().st_size > 65536:
            raise ConfigError("豆包配置文件过大")
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise ConfigError("缺少豆包配置文件：.env.doubao.local") from None
    except (OSError, UnicodeError):
        raise ConfigError("无法读取豆包配置文件") from None
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, raw = line.partition("=")
        key, raw = key.strip(), raw.strip()
        if not sep or key not in ALLOWED_KEYS:
            raise ConfigError("豆包配置文件包含不支持的字段或格式")
        if key in values:
            raise ConfigError(f"豆包配置字段重复：{key}")
        # 保存器采用 JSON 字符串；支持手写单引号，但无 shell 转义或内联注释。
        if raw.startswith('"'):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raise ConfigError(f"配置字段引号格式无效：{key}") from None
        elif raw.startswith("'"):
            if len(raw) < 2 or not raw.endswith("'") or "'" in raw[1:-1]:
                raise ConfigError(f"配置字段引号格式无效：{key}")
            raw = raw[1:-1]
        values[key] = _value(raw, key, allow_empty=True)
    return values


def _from_values(values: dict[str, str]) -> DoubaoConfig:
    return DoubaoConfig(
        api_key=values.get("DOUBAO_API_KEY", ""),
        speaker=values.get("DOUBAO_SPEAKER", DEFAULT_SPEAKER),
        instructions=values.get("DOUBAO_INSTRUCTIONS", DEFAULT_INSTRUCTIONS),
        model=values.get("DOUBAO_MODEL", MODEL),
        url=values.get("DOUBAO_WS_URL", OFFICIAL_URL),
    )


def load_config(path: str | Path | None = None) -> DoubaoConfig:
    """只读取传入文件；调用者无需加载 dotenv 库，也不会读取 .env。"""
    return _from_values(_read_values(Path(path) if path is not None else DEFAULT_CONFIG_PATH))


def config_status(path: str | Path | None = None) -> dict:
    """供 UI 使用，结果不包含凭据，也不代表云端开通或联网验证成功。"""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        values = _read_values(target, missing_ok=True)
        missing = ["DOUBAO_API_KEY"] if not values.get("DOUBAO_API_KEY", "").strip() else []
        if missing:
            return {"configured": False, "missing": missing, "error": "缺少配置字段：DOUBAO_API_KEY"}
        _from_values(values)
    except ConfigError as error:
        return {"configured": False, "missing": [], "error": str(error)}
    return {"configured": True, "missing": [], "error": ""}


def save_config(path: str | Path | None = None, *, api_key: str | None = None,
                speaker: str | None = None, instructions: str | None = None) -> None:
    """原子保存白名单配置；None 表示保留既有值，空字符串不会清除凭据。"""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if target.is_symlink():
        raise ConfigError("豆包配置文件不能是符号链接")
    values = _read_values(target, missing_ok=True)
    for key, value in (("DOUBAO_API_KEY", api_key), ("DOUBAO_SPEAKER", speaker),
                       ("DOUBAO_INSTRUCTIONS", instructions)):
        if value is not None:
            values[key] = _value(value, key)
    config = _from_values(values)
    values = {
        "DOUBAO_API_KEY": config.api_key, "DOUBAO_SPEAKER": config.speaker,
        "DOUBAO_INSTRUCTIONS": config.instructions, "DOUBAO_MODEL": config.model,
        "DOUBAO_WS_URL": config.url,
    }
    content = "# 豆包 3.0 本地私有配置；请勿提交或分享。\n" + "".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items()
    )
    temporary: Path | None = None
    try:
        # 同目录替换避免跨盘移动；异常时原文件仍然完整。
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".doubao-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except OSError:
        raise ConfigError("无法保存豆包配置文件") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_credentials(path: str | Path | None = None, *, api_key: str) -> None:
    """UI 只更新 API Key，不需要先读取或回显已有密钥。"""
    save_config(path, api_key=api_key)
