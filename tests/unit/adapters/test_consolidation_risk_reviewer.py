"""风险复核适配器只发送明确候选和证据，并且不重试。"""

import json

import pytest

from longmemory.adapters.llm.consolidation_risk import (
    RISK_REVIEW_PROMPT,
    OpenAICompatibleConsolidationRiskReviewer,
)
from longmemory.core.memory.consolidation.models import ConsolidationStage
from longmemory.core.memory.consolidation.risk_review import (
    ConsolidationRiskEvidence,
    ConsolidationRiskReviewError,
    ConsolidationRiskReviewInput,
)
from longmemory.infrastructure.config.settings import ModelSettings


def settings():
    return ModelSettings(
        provider="openai_compatible",
        base_url="https://synthetic.invalid/v1",
        api_key="SYNTHETIC_SECRET",
        model="synthetic-model",
    )


def value():
    return ConsolidationRiskReviewInput(
        stage=ConsolidationStage.L1_TO_L2,
        operation="ADD",
        candidate="饮品偏好：用户最近喜欢喝茉莉花茶。",
        evidence=(
            ConsolidationRiskEvidence("l1-a", "用户喜欢喝茉莉花茶。"),
            ConsolidationRiskEvidence("l1-b", "用户最近选择茉莉花茶。"),
        ),
    )


def test_adapter_uses_separate_prompt_and_redacts_key():
    captured = {}

    def transport(_settings, body):
        captured.update(json.loads(body))
        content = (
            '{"schema_version":1,"sensitive":false,'
            '"unresolved_conflict":false,"clarification_allowed":true,'
            '"reason_codes":["low_risk_preference"]}'
        )
        return 200, json.dumps({"choices": [{
            "finish_reason": "stop", "message": {"content": content},
        }]}).encode()

    result = OpenAICompatibleConsolidationRiskReviewer(
        settings(), transport=transport,
    ).review(value())
    assert captured["messages"][0] == {
        "role": "system", "content": RISK_REVIEW_PROMPT,
    }
    payload = json.loads(captured["messages"][1]["content"])
    assert payload["stage"] == "l1_to_l2"
    assert [item["id"] for item in payload["evidence"]] == ["l1-a", "l1-b"]
    assert "SYNTHETIC_SECRET" not in json.dumps(captured)
    assert result.sensitive is False


def test_remote_or_schema_failure_is_redacted_and_not_retried():
    calls = []

    def transport(*args):
        calls.append(args)
        return 403, b"PRIVATE_REMOTE_SENTINEL"

    with pytest.raises(ConsolidationRiskReviewError) as error:
        OpenAICompatibleConsolidationRiskReviewer(
            settings(), transport=transport,
        ).review(value())
    assert "PRIVATE_REMOTE_SENTINEL" not in str(error.value)
    assert len(calls) == 1
