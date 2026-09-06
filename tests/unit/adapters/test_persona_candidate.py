import json

from longmemory.adapters.llm.persona_candidate import (
    PERSONA_CONSOLIDATION_PROMPT,
    PERSONA_PROMPT,
    OpenAICompatiblePersonaProposalProducer,
)
from longmemory.core.common.identifiers import MemorySubjectId
from longmemory.core.memory.l3_persona.models import PersonaBasis, PersonaSourceLayer
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalEvidence,
    PersonaProposalInput,
)
from longmemory.infrastructure.config.settings import ModelSettings


def test_openai_persona_adapter_sends_only_explicit_sources_and_l0():
    captured = {}

    def transport(settings, body):
        captured.update(json.loads(body))
        response = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"schema_version":1,"candidate":null}'
        }}]}
        return 200, json.dumps(response).encode()

    settings = ModelSettings(
        provider="openai_compatible", base_url="https://synthetic.invalid/v1",
        api_key="synthetic", model="synthetic-model",
    )
    source = PersonaProposalInput(
        PersonaSourceLayer.L1, "l1-a", MemorySubjectId("user:self"), "用户喜欢茶。",
        (PersonaProposalEvidence("l0-a", "我喜欢茶。", "2026-09-06"),),
    )
    producer = OpenAICompatiblePersonaProposalProducer(settings, transport=transport)
    producer.propose(basis=PersonaBasis.USER_DECLARED, sources=(source,))

    assert captured["messages"][0] == {"role": "system", "content": PERSONA_PROMPT}
    payload = json.loads(captured["messages"][1]["content"])
    assert payload == {"basis": "user_declared", "sources": [{
        "layer": "l1", "id": "l1-a", "content": "用户喜欢茶。",
        "user_evidence": [{
            "id": "l0-a", "content": "我喜欢茶。",
            "observation_day_utc": "2026-09-06",
        }],
    }]}
    assert "api_key" not in captured


def test_openai_persona_consolidation_sends_active_profile_without_hidden_history():
    captured = {}

    def transport(settings, body):
        captured.update(json.loads(body))
        response = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"schema_version":1,"operation":"NOOP","candidate":null,"replaces":[]}'
        }}]}
        return 200, json.dumps(response).encode()

    settings = ModelSettings(
        provider="openai_compatible", base_url="https://synthetic.invalid/v1",
        api_key="synthetic", model="synthetic-model",
    )
    source = PersonaProposalInput(
        PersonaSourceLayer.L1, "l1-a", MemorySubjectId("user:self"), "用户喜欢茶。",
        (PersonaProposalEvidence("l0-a", "我喜欢茶。", "2026-09-06"),),
    )
    from datetime import UTC, datetime
    from longmemory.core.common.identifiers import PersonaId
    from longmemory.core.memory.l3_persona.models import PersonaKind, PersonaMemory, PersonaStatus
    persona = PersonaMemory(
        id=PersonaId("persona-a"), subject_id=MemorySubjectId("user:self"),
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="饮品偏好", statement="用户喜欢茶。",
        generated_at=datetime(2026, 9, 6, tzinfo=UTC), status=PersonaStatus.ACTIVE,
        generator_name="manual_console", generator_version="1", revision=2,
    )
    producer = OpenAICompatiblePersonaProposalProducer(settings, transport=transport)
    producer.propose_consolidation(
        basis=PersonaBasis.USER_DECLARED, sources=(source,), active_personas=(persona,),
    )

    assert captured["messages"][0] == {"role": "system", "content": PERSONA_CONSOLIDATION_PROMPT}
    payload = json.loads(captured["messages"][1]["content"])
    assert payload["active_personas"] == [{
        "id": "persona-a", "kind": "preference", "label": "饮品偏好",
        "statement": "用户喜欢茶。", "revision": 2,
    }]
    assert set(payload) == {"basis", "sources", "active_personas"}
