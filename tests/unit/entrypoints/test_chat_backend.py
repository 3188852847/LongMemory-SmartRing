from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
from longmemory.infrastructure.config.settings import ModelSettings

import json
import sqlite3

import pytest

from longmemory.adapters.llm.fake import FakeAnswerGenerator
from longmemory.application.chat.contracts import AnswerGenerationError
from test_chat_console import synthetic_backend


@pytest.fixture
def database(tmp_path):
    return tmp_path / "sources.db"


def test_model_health_records_safe_failure_and_explicit_probe_does_not_write_memory(database):
    class Broken:
        def with_role_prompt(self, _prompt):
            return self
        def generate(self, **_kwargs):
            raise AnswerGenerationError("private upstream body", code="model_authentication_failed")
        generate_turn = generate
    backend = synthetic_backend(database, Broken(), provider="openai_compatible", model="synthetic")
    assert backend.info()["model_health"]["state"] == "unchecked"
    health = backend.check_model()
    assert health["state"] == "unavailable" and health["code"] == "model_authentication_failed"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
    result = backend.run("我叫小林", ())
    assert result["error"] == "model_authentication_failed"
    assert "private upstream body" not in json.dumps(result)


def test_model_info_exposes_endpoint_but_never_credentials(database):
    backend = synthetic_backend(database, FakeAnswerGenerator(), provider="openai_compatible",
                          model="synthetic", model_endpoint="http://model.invalid/tenant/v1",
                          insecure_model_transport=True)
    info = backend.info()
    assert info["model_endpoint"] == "http://model.invalid/tenant/v1"
    assert info["insecure_model_transport"] is True
    assert "api_key" not in json.dumps(info).lower()


def test_model_payload_preserves_roles_and_legacy_generate_protocol(database):
    payloads = []
    def transport(settings, body):
        payloads.append(json.loads(body))
        return 200, b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
    generator = OpenAICompatibleAnswerGenerator(
        ModelSettings(provider="openai_compatible", base_url="https://synthetic.invalid/v1", api_key="synthetic", model="test"),
        transport=transport, role_prompt="synthetic role",
    )
    history = ({"role": "user", "content": "上一句"}, {"role": "assistant", "content": "上个回答"})
    result = synthetic_backend(database, generator, provider="openai_compatible").run("继续", history)
    assert result["status"] == "completed"
    assert payloads[0]["messages"][-3:] == [*history, {"role": "user", "content": "继续"}]
    assert payloads[0]["messages"][1]["content"] == "synthetic role"
    generator.generate(query="独立问题", memory_context="")
    assert "上一句" not in json.dumps(payloads[1], ensure_ascii=False)
