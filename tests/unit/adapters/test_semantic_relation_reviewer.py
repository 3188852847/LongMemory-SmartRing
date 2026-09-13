import json

import pytest

from longmemory.adapters.llm.semantic_relation import (
    OpenAICompatibleSemanticRelationReviewer,
    SEMANTIC_RELATION_PROMPT,
)
from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelation,
    SemanticRelationError,
    SemanticRelationPair,
)
from longmemory.infrastructure.config.settings import ModelSettings


PAIR = SemanticRelationPair(
    "pair-a", "memory-a", "memory-b",
    "用户以前住在南京。", "用户现在住在合肥。",
    "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z",
)


def settings():
    return ModelSettings(
        provider="openai_compatible", api_key="test-key",
        base_url="https://example.test/v1", model="test-model",
    )


def response(content, *, finish_reason="stop"):
    return json.dumps({"choices": [{"finish_reason": finish_reason,
                                     "message": {"content": content}}]}).encode()


def valid_review():
    return json.dumps({"schema_version": 1, "decisions": [{
        "pair_id": "pair-a", "relation": "possible_change",
        "reason_code": "explicit_change_over_time",
        "left_quote": "以前住在南京", "right_quote": "现在住在合肥",
    }]}, ensure_ascii=False)


def test_sends_one_bounded_non_thinking_json_request_and_parses_it():
    seen = {}

    def transport(received_settings, body):
        seen.update(json.loads(body))
        assert received_settings == settings()
        return 200, response(valid_review())

    result = OpenAICompatibleSemanticRelationReviewer(
        settings(), transport=transport,
    ).review((PAIR,))

    assert result.decisions[0].relation is SemanticRelation.POSSIBLE_CHANGE
    assert seen["messages"][0]["content"] == SEMANTIC_RELATION_PROMPT
    assert seen["messages"][1]["role"] == "user"
    assert seen["thinking"] == {"type": "disabled"}
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["temperature"] == 0
    assert seen["stream"] is False


def test_invalid_input_stops_before_transport():
    calls = []
    reviewer = OpenAICompatibleSemanticRelationReviewer(
        settings(), transport=lambda *_: calls.append(True),
    )

    with pytest.raises(SemanticRelationError, match="semantic_relation_pair_count_invalid"):
        reviewer.review(())
    assert calls == []


@pytest.mark.parametrize(
    ("status", "payload", "error"),
    [
        (503, b"{}", "semantic_relation_http_error"),
        (200, response(valid_review(), finish_reason="length"),
         "semantic_relation_response_incomplete"),
        (200, b"not-json", "semantic_relation_review_failed"),
    ],
)
def test_remote_or_protocol_failure_is_stable_and_never_retried(status, payload, error):
    calls = []

    def transport(*_):
        calls.append(True)
        return status, payload

    with pytest.raises(SemanticRelationError, match=error):
        OpenAICompatibleSemanticRelationReviewer(
            settings(), transport=transport,
        ).review((PAIR,))
    assert len(calls) == 1
