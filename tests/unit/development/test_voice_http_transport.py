"""只用公开 SDK 扩展接口的合成连接策略验证，不读配置或请求网络。"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
from voice_http_transport import create_voice_openai_client, install_voice_http_transport


@pytest.fixture
def dependencies():
    sdk_calls, http_calls = [], []

    class HttpClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            http_calls.append(self)
        def close(self): self.closed = True
        @property
        def is_closed(self): return self.closed

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            sdk_calls.append(self)
        def close(self):
            self.kwargs["http_client"].close()

    sdk = SimpleNamespace(OpenAI=Client, DefaultHttpxClient=HttpClient,
                          DEFAULT_CONNECTION_LIMITS=SimpleNamespace(
                              max_connections=1000, max_keepalive_connections=100))
    httpx = SimpleNamespace(Limits=lambda **kwargs: SimpleNamespace(**kwargs))
    return SimpleNamespace(sdk=sdk, httpx=httpx, sdk_calls=sdk_calls, http_calls=http_calls)


def test_official_client_preserves_all_sdk_options_and_owns_one_connection_pool(dependencies):
    d = dependencies
    timeout = object()
    original = dict(api_key="synthetic-key", base_url="https://api.deepseek.com/v1", timeout=timeout,
                    organization="synthetic-org", project="synthetic-project", max_retries=0,
                    default_headers={"X-Synthetic": "value"}, default_query={"synthetic": "value"},
                    websocket_base_url="wss://example.invalid", webhook_secret="synthetic-webhook")
    saved = dict(original)
    client = create_voice_openai_client(d.sdk, d.httpx, **original)
    assert original == saved
    assert {key: value for key, value in client.kwargs.items() if key != "http_client"} == original
    assert len(d.sdk_calls) == len(d.http_calls) == 1
    limits = d.http_calls[0].kwargs["limits"]
    assert vars(limits) == dict(max_connections=1000, max_keepalive_connections=100, keepalive_expiry=120.0)
    # 未传代理、verify、trust_env 或 transport，继续使用 SDK / HTTPX 的公开默认。
    assert set(d.http_calls[0].kwargs) == {"limits", "http2"}
    assert d.http_calls[0].kwargs["http2"] is True
    assert client.kwargs["timeout"] is timeout
    assert not d.http_calls[0].closed
    client.close()
    assert d.http_calls[0].closed


@pytest.mark.parametrize("base_url", [
    "http://api.deepseek.com/v1", "https://api.deepseek.com.evil.invalid/v1",
    "https://example.invalid/v1", "https://deepseek.com/v1",
    "https://api.deepseek.com/v1?secret=synthetic", "https://api.deepseek.com/v1#fragment",
    "https://user:synthetic@api.deepseek.com/v1", "https://api.deepseek.com:8443/v1",
    "https://api.deepseek.com/custom/v1", "https://api.deepseek.com:invalid/v1", None,
])
def test_unverified_endpoints_keep_original_client_options(dependencies, base_url):
    d = dependencies
    client = create_voice_openai_client(d.sdk, d.httpx, api_key="synthetic", base_url=base_url)
    assert client.kwargs == dict(api_key="synthetic", base_url=base_url)
    assert d.http_calls == []


def test_custom_client_with_its_proxy_and_tls_settings_is_not_replaced(dependencies):
    d = dependencies
    custom_client = object()
    client = create_voice_openai_client(d.sdk, d.httpx, api_key="synthetic",
                                        base_url="https://api.deepseek.com/v1", http_client=custom_client)
    assert client.kwargs["http_client"] is custom_client
    assert d.http_calls == []


@pytest.mark.parametrize("error", [
    ModuleNotFoundError("synthetic h2 unavailable", name="h2"),
    ImportError("synthetic h2 API unavailable", name="h2.connection"),
    ImportError("synthetic hpack unavailable", name="hpack"),
    ImportError("Using http2=True, but the 'h2' package is not installed. "
                "Make sure to install httpx using `pip install httpx[http2]`."),
])
def test_http2_optional_dependency_failure_returns_original_sdk_constructor(dependencies, error):
    d = dependencies
    class UnavailableClient:
        def __init__(self, **kwargs): raise error
    d.sdk.DefaultHttpxClient = UnavailableClient
    options = dict(api_key="synthetic", base_url="https://api.deepseek.com/v1", timeout=300,
                   organization="synthetic-org", default_headers={"X-Synthetic": "preserved"})
    client = create_voice_openai_client(d.sdk, d.httpx, **options)
    assert client.kwargs == options
    assert len(d.sdk_calls) == 1
    assert d.http_calls == []


@pytest.mark.parametrize("error", [
    ImportError("synthetic socks proxy unavailable", name="socksio"),
    ValueError("synthetic TLS configuration invalid"),
    TypeError("synthetic unsupported explicit parameter"),
])
def test_unrelated_http_configuration_errors_are_not_silently_hidden(dependencies, error):
    d = dependencies
    class InvalidClient:
        def __init__(self, **kwargs): raise error
    d.sdk.DefaultHttpxClient = InvalidClient
    with pytest.raises(type(error)) as raised:
        create_voice_openai_client(d.sdk, d.httpx, api_key="synthetic", base_url="https://api.deepseek.com/v1")
    assert raised.value is error
    assert d.sdk_calls == []


def test_failed_sdk_construction_closes_new_http_client(dependencies):
    d = dependencies
    def fail(**kwargs): raise ValueError("synthetic construction failure")
    d.sdk.OpenAI = fail
    with pytest.raises(ValueError, match="synthetic construction failure"):
        create_voice_openai_client(d.sdk, d.httpx, api_key="synthetic", base_url="https://api.deepseek.com/v1")
    assert len(d.http_calls) == 1 and d.http_calls[0].closed


def test_owned_http_client_also_closes_when_released_without_sdk_close(dependencies):
    d = dependencies
    client = create_voice_openai_client(d.sdk, d.httpx, api_key="synthetic",
                                        base_url="https://api.deepseek.com/v1")
    http_client = client.kwargs["http_client"]
    http_client.__del__()
    assert http_client.closed
    http_client.__del__()  # 回收与显式 close 相遇也可重复调用。


def test_installer_is_provider_local_idempotent_and_disabled_by_default(dependencies):
    d = dependencies
    provider = SimpleNamespace(openai=d.sdk, httpx=d.httpx)
    other_provider = SimpleNamespace(openai=d.sdk)
    original_constructor = d.sdk.OpenAI
    install_voice_http_transport(provider)
    assert provider.openai is d.sdk
    install_voice_http_transport(provider, enabled=True)
    proxy = provider.openai
    install_voice_http_transport(provider, enabled=True)
    assert provider.openai is proxy
    assert other_provider.openai is d.sdk
    assert d.sdk.OpenAI is original_constructor
    provider.openai.OpenAI(api_key="synthetic", base_url="https://api.deepseek.com/v1")
    assert len(d.http_calls) == 1
    other_provider.openai.OpenAI(api_key="synthetic", base_url="https://api.deepseek.com/v1")
    assert len(d.http_calls) == 1  # 其他调用者仍走旧构造，不影响网页策略。
    assert proxy.DEFAULT_CONNECTION_LIMITS is d.sdk.DEFAULT_CONNECTION_LIMITS
