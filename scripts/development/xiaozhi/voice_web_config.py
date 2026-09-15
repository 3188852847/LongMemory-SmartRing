"""联网搜索的本机凭据入口；不联网、不加载个人数据库。"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import tempfile

CONFIG_PATH = Path(__file__).resolve().parents[3] / ".env.web-search.local"
PROVIDERS = {"tavily", "metaso"}


@dataclass(frozen=True)
class SearchConfig:
    provider: str = "disabled"
    api_key: str = field(default="", repr=False)


def load_config(path=CONFIG_PATH):
    if not path.is_file():
        return SearchConfig()
    if path.stat().st_size > 4096:
        raise ValueError("search_config_invalid")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in {"PROVIDER", "API_KEY"} or key in values:
            raise ValueError("search_config_invalid")
        values[key] = value
    provider, api_key = values.get("PROVIDER", "disabled"), values.get("API_KEY", "")
    if provider != "disabled" and provider not in PROVIDERS:
        raise ValueError("search_provider_invalid")
    if provider != "disabled" and not re.fullmatch(r"[A-Za-z0-9._-]{8,512}", api_key):
        raise ValueError("search_key_invalid")
    return SearchConfig(provider, api_key)


def save_config(path, *, provider, api_key=""):
    old = load_config(path)  # 不覆盖损坏或未知格式的用户文件。
    if provider not in PROVIDERS | {"disabled"}:
        raise ValueError("search_provider_invalid")
    if not api_key and old.provider == provider:
        api_key = old.api_key
    if provider == "disabled":
        api_key = ""
    elif not re.fullmatch(r"[A-Za-z0-9._-]{8,512}", api_key):
        raise ValueError("search_key_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".web-search-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"PROVIDER={provider}\nAPI_KEY={api_key}\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
