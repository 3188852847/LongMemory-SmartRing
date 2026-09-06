"""L3 整理建议只能表达受控的 ADD / UPDATE / NOOP。"""

from datetime import UTC, datetime
import json

import pytest

from longmemory.application.persona_management.consolidation_service import PersonaConsolidationService
from longmemory.core.common.identifiers import MemorySubjectId, PersonaId
from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationOperation,
    parse_persona_consolidation,
)
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaMemory,
    PersonaSourceLayer,
    PersonaStatus,
)
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)


def active(identifier: str, kind: PersonaKind = PersonaKind.PREFERENCE) -> PersonaMemory:
    return PersonaMemory(
        id=PersonaId(identifier),
        subject_id=MemorySubjectId("user:self"),
        kind=kind,
        basis=PersonaBasis.USER_DECLARED,
        label="旧画像",
        statement="用户喜欢乌龙茶。",
        generated_at=datetime(2026, 9, 6, tzinfo=UTC),
        status=PersonaStatus.ACTIVE,
        generator_name="manual_console",
        generator_version="1",
        revision=2,
    )


def payload(operation: str, *, candidate=True, replaces=()):
    body = {
        "schema_version": 1,
        "operation": operation,
        "candidate": ({
            "kind": "preference",
            "label": "饮品偏好",
            "statement": "用户现在偏好清淡乌龙茶。",
            "sources": [{"layer": "l1", "id": "l1-new"}],
        } if candidate else None),
        "replaces": list(replaces),
    }
    return json.dumps(body, ensure_ascii=False)


def parse(raw: str, personas=()):
    return parse_persona_consolidation(
        raw,
        basis=PersonaBasis.USER_DECLARED,
        allowed_source_refs=((PersonaSourceLayer.L1, "l1-new"),),
        active_personas=tuple(personas),
    )


def source_inputs():
    return tuple(PersonaProposalInput(
        PersonaSourceLayer.L1, f"l1-{index}", MemorySubjectId("user:self"), text,
        (PersonaProposalEvidence(f"l0-{index}", original, day),),
    ) for index, text, original, day in (
        ("new", "用户现在喜欢清淡乌龙茶。", "我现在更喜欢清淡乌龙茶。", "2026-09-06"),
    ))


def test_consolidation_accepts_add_update_and_noop_contracts():
    added = parse(payload("ADD"))
    updated = parse(payload("UPDATE", replaces=("old",)), (active("old"),))
    noop = parse(payload("NOOP", candidate=False))

    assert added.operation == PersonaConsolidationOperation.ADD
    assert added.candidate.statement == "用户现在偏好清淡乌龙茶。"
    assert added.replaces == ()
    assert updated.operation == PersonaConsolidationOperation.UPDATE
    assert updated.replaces == (PersonaId("old"),)
    assert noop.operation == PersonaConsolidationOperation.NOOP
    assert noop.candidate is None and noop.replaces == ()


@pytest.mark.parametrize("raw,personas", [
    (payload("ADD", replaces=("old",)), (active("old"),)),
    (payload("UPDATE"), (active("old"),)),
    (payload("UPDATE", replaces=("missing",)), (active("old"),)),
    (payload("UPDATE", replaces=("old",)), (active("old", PersonaKind.HABIT),)),
    (payload("NOOP"), ()),
    (payload("NOOP", candidate=False, replaces=("old",)), (active("old"),)),
])
def test_consolidation_rejects_ambiguous_or_unauthorized_operations(raw, personas):
    with pytest.raises(PersonaProposalError, match="persona_consolidation_schema_invalid"):
        parse(raw, personas)


def test_consolidation_rejects_sources_outside_explicit_input():
    raw = payload("ADD").replace("l1-new", "l1-hidden")
    with pytest.raises(PersonaProposalError, match="persona_proposal_schema_invalid"):
        parse(raw)


def test_consolidation_service_returns_reviewable_update_without_writing():
    class Producer:
        calls = 0

        def propose_consolidation(self, *, basis, sources, active_personas):
            self.calls += 1
            assert active_personas[0].id == PersonaId("old")
            return payload("UPDATE", replaces=("old",))

    producer = Producer()
    suggestion = PersonaConsolidationService(producer).preview(
        basis=PersonaBasis.USER_DECLARED,
        sources=source_inputs(),
        active_personas=(active("old"),),
    )
    assert suggestion.operation == PersonaConsolidationOperation.UPDATE
    assert suggestion.replaces == (PersonaId("old"),)
    assert producer.calls == 1
