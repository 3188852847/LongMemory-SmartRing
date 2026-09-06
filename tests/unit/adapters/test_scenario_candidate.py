"""L2 模型适配器只使用内存传输替身，不访问学校服务。"""

import json

import pytest

from longmemory.adapters.llm.scenario_candidate import (
    SCENARIO_PROMPT,
    OpenAICompatibleScenarioProposalProducer,
)
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l2_scenario.proposals import ScenarioProposalError, ScenarioProposalInput
from longmemory.infrastructure.config.settings import ModelSettings


def _settings():
    return ModelSettings(provider="openai_compatible", base_url="https://example.invalid/v1",
                         api_key="SYNTHETIC_SECRET", model="synthetic")


def _sources():
    return (
        ScenarioProposalInput(MemoryId("l1-a"), MemorySubjectId("user:self"), "事实一", ("l0-a",)),
        ScenarioProposalInput(MemoryId("l1-b"), MemorySubjectId("user:self"), "事实二", ("l0-b",)),
    )


def test_request_contains_only_prompt_and_selected_l1_data():
    answer = '{"schema_version":2,"candidate":{"title":"合成","summary":"合成摘要",' \
             '"source_memory_ids":["l1-a","l1-b"]}}'
    calls = []

    def transport(settings, payload):
        data = json.loads(payload)
        calls.append(data)
        assert data["messages"][0] == {"role": "system", "content": SCENARIO_PROMPT}
        sent = json.loads(data["messages"][1]["content"])
        assert sent == {"memories": [{"id": "l1-a", "content": "事实一"},
                                      {"id": "l1-b", "content": "事实二"}]}
        assert "l0-a" not in payload.decode() and "SYNTHETIC_SECRET" not in payload.decode()
        return 200, json.dumps({"choices": [{
            "finish_reason": "stop", "message": {"content": answer}
        }]}).encode()

    result = OpenAICompatibleScenarioProposalProducer(
        _settings(), transport=transport
    ).propose(sources=_sources())
    assert result == answer and len(calls) == 1


def test_remote_failure_is_redacted_and_not_retried():
    calls = []

    def transport(*args):
        calls.append(args)
        return 403, b"PRIVATE_REMOTE_SENTINEL"

    with pytest.raises(ScenarioProposalError) as error:
        OpenAICompatibleScenarioProposalProducer(
            _settings(), transport=transport
        ).propose(sources=_sources())
    assert "PRIVATE_REMOTE_SENTINEL" not in str(error.value)
    assert len(calls) == 1
