"""从环境变量读取配置；.env 由 uv 加载，不自行实现配置文件解析器。"""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ModelSettings:
    """模型连接参数。repr 隐藏 Key，校验错误也不回显输入值。"""

    provider: str = "fake"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout_seconds: float = 30.0
    max_tokens: int = 512
    allow_http: bool = False

    def __post_init__(self) -> None:
        if self.provider not in {"fake", "openai_compatible"}:
            raise ValueError("模型 provider 必须为 fake 或 openai_compatible。")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("模型超时必须是正的有限秒数。")
        if not 1 <= self.max_tokens <= 32768:
            raise ValueError("max_tokens 必须在 1 到 32768 之间。")
        if self.provider == "fake":
            return
        url = urlsplit(self.base_url)
        try:
            port = url.port
        except ValueError:
            raise ValueError("模型 URL 端口无效。") from None
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or any(c.isspace() for c in self.base_url)):
            raise ValueError("模型 URL 必须是无凭据、查询参数和片段的 HTTP(S) 地址。")
        if port == 0:
            raise ValueError("模型 URL 端口不能为 0。")
        if url.scheme == "http" and not self.allow_http:
            raise ValueError("HTTP 不加密。校园网合成验证需显式设置 LONGMEMORY_LLM_ALLOW_HTTP=true。")
        if not self.model.strip() or not self.api_key.strip():
            raise ValueError("真实模型需要设置 MODEL 和 API_KEY 环境变量。")
        if any(c in self.api_key for c in "\r\n"):
            raise ValueError("API_KEY 不允许换行。")
        if not self.api_key.isascii():
            raise ValueError("API_KEY 必须为合法的 ASCII 凭据。")


def load_model_settings(
    environ: Mapping[str, str] | None = None,
    *,
    provider: str | None = None,
) -> ModelSettings:
    """显式 CLI 选择覆盖环境选择；默认 Fake 保证离线可复现。"""

    env = os.environ if environ is None else environ
    try:
        timeout = float(env.get("LONGMEMORY_LLM_TIMEOUT_SECONDS", "30"))
        tokens = int(env.get("LONGMEMORY_LLM_MAX_TOKENS", "512"))
    except ValueError:
        raise ValueError("模型 timeout/max_tokens 配置必须为数值。") from None
    allow_http = env.get("LONGMEMORY_LLM_ALLOW_HTTP", "false").lower()
    if allow_http not in {"true", "false"}:
        raise ValueError("LONGMEMORY_LLM_ALLOW_HTTP 只能为 true 或 false。")
    return ModelSettings(
        provider=provider or env.get("LONGMEMORY_LLM_PROVIDER", "fake"),
        base_url=env.get("LONGMEMORY_LLM_BASE_URL", "").rstrip("/"),
        api_key=env.get("LONGMEMORY_LLM_API_KEY", ""),
        model=env.get("LONGMEMORY_LLM_MODEL", ""),
        timeout_seconds=timeout,
        max_tokens=tokens,
        allow_http=allow_http == "true",
    )


def database_path_from_env() -> Path:
    return Path(os.environ.get("LONGMEMORY_DATABASE_PATH", "data/databases/longmemory.db"))
