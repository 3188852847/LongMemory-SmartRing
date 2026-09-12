import json

import pytest

from longmemory.adapters.llm.evidence_sufficiency import (
    OpenAICompatibleEvidenceSufficiencyGate,
    SUFFICIENCY_GATE_PROMPT_SHA256,
)
from longmemory.core.memory.retrieval.sufficiency import (
    EvidenceCandidate,
    EvidenceSufficiencyError,
    EvidenceSufficiencyInput,
)
from longmemory.infrastructure.config.settings import ModelSettings


def _settings():
    return ModelSettings(
        provider="openai_compatible", base_url="https://synthetic.invalid/v1",
        api_key="synthetic", model="test-model",
    )


def test_openai_gate_sends_untrusted_candidates_as_json_and_parses_response():
    captured = {}

    def transport(_settings, body):
        captured.update(json.loads(body))
        response = {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "schema_version": 1,
                "decisions": [{
                    "id": "cat", "supports_answer": False,
                    "reason_code": "missing_attribute",
                }],
            })}}],
        }
        return 200, json.dumps(response).encode()

    gate = OpenAICompatibleEvidenceSufficiencyGate(_settings(), transport=transport)
    review = gate.review(EvidenceSufficiencyInput(
        query="豆包的毛色是什么？",
        candidates=(EvidenceCandidate("cat", "用户养了一只叫豆包的猫。"),),
    ))

    assert review.supported_ids == ()
    assert captured["model"] == "test-model"
    assert captured["stream"] is False
    assert "<script>" not in captured["messages"][0]["content"]
    assert len(SUFFICIENCY_GATE_PROMPT_SHA256) == 64


def test_openai_gate_fails_closed_without_retry_on_invalid_response():
    calls = 0

    def transport(_settings, _body):
        nonlocal calls
        calls += 1
        return 200, b'{"choices":[]}'

    gate = OpenAICompatibleEvidenceSufficiencyGate(_settings(), transport=transport)
    with pytest.raises(EvidenceSufficiencyError) as error:
        gate.review(EvidenceSufficiencyInput(
            query="question", candidates=(EvidenceCandidate("one", "evidence"),),
        ))

    assert str(error.value) == "evidence_sufficiency_review_failed"
    assert calls == 1
