"""全程内存模拟，不访问校园网，不使用真实 Key。"""

import json

import pytest

from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator, send_request
from longmemory.application.chat.contracts import AnswerGenerationError
from longmemory.infrastructure.config.settings import ModelSettings, load_model_settings


def settings(**overrides):
    return ModelSettings(**{
        "provider": "openai_compatible", "base_url": "https://model.example/v1",
        "model": "test-model", "api_key": "synthetic-secret", **overrides,
    })


def test_request_uses_separate_evidence_and_question():
    calls = []

    def transport(config, body):
        calls.append(json.loads(body))
        return 200, b'{"choices":[{"message":{"content":"OK"},"finish_reason":"stop"}]}'

    generator = OpenAICompatibleAnswerGenerator(settings(), transport=transport)
    assert generator.generate(query="问题", memory_context="合成证据") == "OK"
    payload = calls[0]
    assert payload["stream"] is False
    assert payload["model"] == "test-model"
    assert payload["messages"][-1] == {"role": "user", "content": "问题"}
    assert json.loads(payload["messages"][1]["content"])["memory_evidence"] == "合成证据"
    assert "synthetic-secret" not in json.dumps(payload)


@pytest.mark.parametrize("status,payload", [
    (401, b"synthetic-secret private-input"), (404, b"private-input"),
    (302, b"redirect"), (429, b"busy"), (500, b"server"),
    (200, b"not json"), (200, b'{"choices":[]}'),
    (200, b'{"choices":[{"message":{"content":null}}]}'),
    (200, b'{"choices":[{"message":{"content":" "}}]}'),
    (200, b'{"choices":[{"message":{"content":"partial"},"finish_reason":"length"}]}'),
])
def test_failure_is_safe_and_does_not_fall_back(status, payload):
    generator = OpenAICompatibleAnswerGenerator(settings(), transport=lambda *_: (status, payload))
    with pytest.raises(AnswerGenerationError) as error:
        generator.generate(query="private-input", memory_context="")
    assert "synthetic-secret" not in str(error.value)
    assert "private-input" not in str(error.value)


def test_timeout_has_no_remote_exception_text():
    def fail(*_):
        raise TimeoutError("synthetic-secret")
    with pytest.raises(AnswerGenerationError) as error:
        OpenAICompatibleAnswerGenerator(settings(), transport=fail).generate(query="x", memory_context="")
    assert "synthetic-secret" not in str(error.value)
    assert error.value.code == "model_request_timeout"


@pytest.mark.parametrize("status,code", [
    (401, "model_authentication_failed"), (403, "model_authentication_failed"),
    (404, "model_deployment_not_found"), (429, "model_rate_limited"),
    (500, "model_service_unavailable"), (503, "model_service_unavailable"),
    (400, "model_request_rejected"),
])
def test_http_failure_has_safe_actionable_code(status, code):
    generator = OpenAICompatibleAnswerGenerator(settings(), transport=lambda *_: (status, b"private"))
    with pytest.raises(AnswerGenerationError) as error:
        generator.generate(query="private-input", memory_context="private-memory")
    assert error.value.code == code
    assert "private" not in str(error.value)


@pytest.mark.parametrize("overrides", [
    {"base_url": "http://model.example/v1"}, {"base_url": "https://user:pass@model.example/v1"},
    {"base_url": "https://model.example/v1?key=value"}, {"api_key": ""},
    {"model": ""}, {"timeout_seconds": float("nan")}, {"max_tokens": 0},
])
def test_invalid_config_fails_before_network(overrides):
    with pytest.raises(ValueError):
        settings(**overrides)


def test_env_defaults_and_secret_repr():
    assert load_model_settings({}).provider == "fake"
    assert "synthetic-secret" not in repr(settings())
    assert settings(base_url="http://model.example/v1", allow_http=True).allow_http


def test_transport_headers_path_timeout_and_close(monkeypatch):
    calls = []

    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))
        def request(self, method, path, body, headers):
            calls.append((method, path, headers))
        def getresponse(self):
            return self
        status = 200
        def read(self, size):
            return b"{}"
        def close(self):
            calls.append("closed")

    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    assert send_request(settings(), b"{}") == (200, b"{}")
    assert calls[0] == ("model.example", None, 30)
    assert calls[1][0:2] == ("POST", "/v1/chat/completions")
    assert calls[1][2]["Authorization"] == "Bearer synthetic-secret"
    assert calls[-1] == "closed"
