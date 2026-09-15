"""为官方 DeepSeek 圆屏请求启用 HTTP/2 和连接复用，不改变全局 SDK。"""

from urllib.parse import urlsplit


KEEPALIVE_SECONDS = 120.0


def _owned_http_client(sdk, limits):
    """补齐默认 SDK 包装器的回收行为，仍只用 HTTPX 的公开关闭接口。"""
    class VoiceHttpClient(sdk.DefaultHttpxClient):
        def __del__(self):
            # SDK 在显式传入 DefaultHttpxClient 时不会再给它包默认析构器。
            # provider 被回收而没有显式 close 时也释放连接；关闭必须幂等。
            try:
                if not self.is_closed:
                    self.close()
            except Exception:
                pass

    return VoiceHttpClient(limits=limits, http2=True)


def _http2_import_unavailable(error):
    """只识别 HTTP/2 可选依赖缺失；其他代理、证书或配置错误仍应报错。"""
    name = getattr(error, "name", None)
    if isinstance(name, str) and name.split(".", 1)[0] in {"h2", "hpack", "hyperframe"}:
        return True
    # 已安装 HTTPX 会重新抛出无 name 的固定 ImportError，不保留原异常。
    return str(error).startswith("Using http2=True, but the 'h2' package is not installed.")


def _official_deepseek(base_url):
    """只识别已核实官方地址，不把相似域名、代理或其他兼容服务纳入优化。"""
    try:
        url = urlsplit(str(base_url))
        return (
            url.scheme == "https" and url.hostname == "api.deepseek.com"
            and url.port in (None, 443) and not url.username and not url.password
            and not url.query and not url.fragment and url.path.rstrip("/") in ("", "/v1")
        )
    except (TypeError, ValueError):
        return False


def create_voice_openai_client(sdk, httpx_module, **kwargs):
    """构造一次独立客户端；SDK 仍负责认证、超时、代理默认和最终关闭。

    DefaultHttpxClient 是 SDK 的公开扩展入口，保留其超时、重定向及 HTTPX
    的环境代理/TLS 默认值。所有 OpenAI 构造参数原样传递，仅补充没有显式
    指定的 http_client。已有自定义客户端可能含代理/证书等设置，必须保留。
    """
    if not _official_deepseek(kwargs.get("base_url")) or kwargs.get("http_client") is not None:
        return sdk.OpenAI(**kwargs)
    defaults = sdk.DEFAULT_CONNECTION_LIMITS
    try:
        http_client = _owned_http_client(sdk, httpx_module.Limits(
            max_connections=defaults.max_connections,
            max_keepalive_connections=defaults.max_keepalive_connections,
            keepalive_expiry=KEEPALIVE_SECONDS,
        ))
    except ImportError as error:
        if not _http2_import_unavailable(error):
            raise
        # 只回到调用方原有 SDK 构造，不联网安装依赖，也不以 HTTP/1 的
        # 120 秒寿命冒充已经验证成功的 HTTP/2 复用策略。
        return sdk.OpenAI(**kwargs)
    try:
        # 不先创建旧客户端，也不用 with_options 共享底层连接，避免旧客户端
        # 关闭时把新客户端的连接池一并关闭。只把这一个新客户端交给 SDK。
        return sdk.OpenAI(**{**kwargs, "http_client": http_client})
    except BaseException:
        try:
            http_client.close()
        except Exception:
            pass  # 保留原构造异常；不输出第三方错误或认证选项。
        raise


class _OpenAIModuleProxy:
    def __init__(self, sdk, httpx_module):
        self._sdk = sdk
        self._httpx = httpx_module

    def __getattr__(self, name):
        return getattr(self._sdk, name)

    def OpenAI(self, **kwargs):
        return create_voice_openai_client(self._sdk, self._httpx, **kwargs)


def install_voice_http_transport(provider_module, *, enabled=False):
    """在 provider 实例创建前安装；原策略或尚未通过基准时不改变任何引用。

    仅替换该语音 provider 模块自己的 openai 名称，不修改 SDK 模块本身，
    不影响网页或其他客户端。启动后切换策略要求重启独立语音进程。
    """
    if not enabled or isinstance(provider_module.openai, _OpenAIModuleProxy):
        return
    provider_module.openai = _OpenAIModuleProxy(provider_module.openai, provider_module.httpx)
