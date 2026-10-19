"""Hy 专属显式配置；不读取 .env、共享私有配置或隐含 API Key。"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from .sdk_bridge import SDK_VERSION


@dataclass(frozen=True)
class Endpoint:
    base_url: str = "https://blocked.invalid/v1"
    model: str = "unconfigured"
    api_key: str = field(default="synthetic-disabled", repr=False)

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("hy_endpoint_requires_explicit_https")
        if not self.model.strip() or not self.api_key.strip():
            raise ValueError("hy_endpoint_incomplete")


@dataclass(frozen=True)
class HySettings:
    user_id: str
    agent_id: str = "v_synthetic"
    embedding_dimensions: int = 8
    llm: Endpoint = field(default_factory=Endpoint)
    embedding: Endpoint = field(default_factory=Endpoint)
    network_authorized: bool = False
    max_external_requests: int = 0
    timeout_seconds: int = 60
    max_output_tokens: int = 1024
    include_profile: bool = False
    sdk_version: str = SDK_VERSION
    model_mode: str = "disabled"

    def __post_init__(self):
        if self.sdk_version != SDK_VERSION or not self.user_id.strip() or not self.agent_id.strip():
            raise ValueError("hy_identity_invalid")
        if type(self.embedding_dimensions) is not int or not 1 <= self.embedding_dimensions <= 65536:
            raise ValueError("hy_dimensions_invalid")
        if type(self.network_authorized) is not bool or type(self.include_profile) is not bool:
            raise ValueError("hy_flag_invalid")
        if self.model_mode not in {"disabled", "synthetic_transport"} or (self.network_authorized and self.model_mode == "synthetic_transport"):
            raise ValueError("hy_model_mode_invalid")
        for value, maximum in ((self.max_external_requests, 100000), (self.timeout_seconds, 600), (self.max_output_tokens, 16000)):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("hy_budget_invalid")
        if self.timeout_seconds == 0 or self.max_output_tokens == 0:
            raise ValueError("hy_budget_invalid")
        if self.network_authorized and (self.max_external_requests == 0 or any(
                endpoint.base_url == Endpoint().base_url or endpoint.model == "unconfigured"
                or endpoint.api_key == "synthetic-disabled" for endpoint in (self.llm, self.embedding))):
            raise ValueError("hy_network_configuration_incomplete")

    def wire(self) -> dict:
        """只给子进程 stdin；含显式凭据，禁止写入报告/argv/日志。"""
        return asdict(self)

    def public(self) -> dict:
        result = asdict(self)
        for name in ("llm", "embedding"):
            endpoint = result[name]
            endpoint.pop("api_key")
            endpoint["endpoint_sha256"] = hashlib.sha256(endpoint.pop("base_url").encode()).hexdigest()
        return result

    def identity(self) -> str:
        # 网络授权/请求预算是本次运行策略，不改变持久库的模型/维度身份。
        public = self.public()
        for key in ("network_authorized", "max_external_requests", "timeout_seconds", "max_output_tokens"):
            public.pop(key)
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_wire(cls, data: dict):
        data = dict(data)
        for name in ("llm", "embedding"):
            data[name] = Endpoint(**data[name])
        return cls(**data)


def load_offline_settings(path: Path) -> HySettings:
    """CLI 只接受离线无密钥文件；真实配置由受授权装配者显式构造。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"user_id", "agent_id", "embedding_dimensions", "timeout_seconds", "max_output_tokens", "include_profile", "sdk_version", "model_mode"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("hy_offline_config_unknown_field")
    return HySettings(**data)
