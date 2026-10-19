"""Hy日用的回环模型投影与固定预算暂停回执，Python3.10标准库桥。"""

import json
import os
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None


def validate_configuration(body):
    keys = {"version", "base_url", "api_key", "model_name", "max_tokens", "timeout", "max_retries"}
    if not isinstance(body, dict) or set(body) != keys or body["version"] != 1:
        raise ValueError("owned_model_configuration_invalid")
    url = urlsplit(body["base_url"])
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port in {None, 0, 8767, 8000, 8003}
            or url.path != "/voice/v1" or url.username or url.password or url.query or url.fragment
            or not isinstance(body["api_key"], str) or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", body["api_key"]) is None
            or not isinstance(body["model_name"], str) or not 1 <= len(body["model_name"]) <= 200
            or any(ord(char) < 32 or ord(char) == 127 for char in body["model_name"])
            or type(body["max_tokens"]) is not int or not 1 <= body["max_tokens"] <= 8192
            or type(body["timeout"]) not in (int, float) or not 0 < body["timeout"] <= 1200
            or type(body["max_retries"]) is not int or body["max_retries"] != 0):
        raise ValueError("owned_model_configuration_invalid")
    return body


def load_owned_configuration(timeout=120):
    url = urlsplit(os.environ.get("LONGMEMORY_RUNTIME_URL", ""))
    token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN", "")
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port is None
            or url.path != "/api/internal/memory/prepare" or url.username or url.password
            or url.query or url.fragment or re.fullmatch(r"[0-9a-f]{64}", token) is None):
        raise ValueError("owned_model_runtime_authority_invalid")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url._replace(path="/api/internal/memory/model-configuration").geturl(),
                      headers={"Authorization": "Bearer " + token})
    deadline = time.monotonic() + timeout
    while True:
        try:
            with opener.open(request, timeout=2) as response:
                data = response.read(8193)
                if len(data) > 8192:
                    raise ValueError("owned_model_configuration_large")
                return validate_configuration(json.loads(data))
        except HTTPError as error:
            if error.code not in {503}:
                raise ValueError("owned_model_runtime_rejected") from None
        except OSError:
            pass  # 只重读启动状态，不重试任何模型/记忆写入。
        if time.monotonic() >= deadline:
            raise ValueError("owned_model_runtime_not_ready")
        time.sleep(.25)


class BudgetNoticeLLM:
    def __init__(self, original, memory):
        self.original, self.memory = original, memory

    def __getattr__(self, name): return getattr(self.original, name)

    def response(self, *args, **kwargs):
        notice = self.memory.fixed_reply_for_current_turn()
        if notice:
            yield notice
        else:
            yield from self.original.response(*args, **kwargs)

    def response_with_functions(self, *args, **kwargs):
        notice = self.memory.fixed_reply_for_current_turn()
        if notice:
            yield notice, None
        else:
            yield from self.original.response_with_functions(*args, **kwargs)


def install_no_retry_gateway_client(provider_module):
    original = provider_module.openai
    class Proxy:
        def __getattr__(self, name): return getattr(original, name)
        def OpenAI(self, **kwargs):
            url = urlsplit(str(kwargs.get("base_url", "")))
            if url.scheme != "http" or url.hostname != "127.0.0.1" or url.path != "/voice/v1":
                raise ValueError("hy_voice_requires_owned_gateway")
            return original.OpenAI(**{**kwargs, "max_retries": 0})
    provider_module.openai = Proxy()
