import pytest

from longmemory.application.persona_management.proposal_service import PersonaProposalService
from longmemory.core.common.identifiers import MemorySubjectId
from longmemory.core.memory.l3_persona.models import PersonaBasis, PersonaSourceLayer
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)


def sources():
    return tuple(PersonaProposalInput(
        PersonaSourceLayer.L1, f"l1-{name}", MemorySubjectId("user:self"), content,
        (PersonaProposalEvidence(f"l0-{name}", original, day),),
    ) for name, content, original, day in (
        ("a", "用户一般下午聊天。", "我一般下午找你聊天。", "2026-09-05"),
        ("b", "用户今天下午聊天。", "今天下午我又来了。", "2026-09-06"),
        ("c", "下午聊天让用户放松。", "下午聊一会让我放松。", "2026-09-06"),
    ))


def test_preview_validates_inferred_evidence_before_and_after_model():
    class Producer:
        calls = 0

        def propose(self, *, basis, sources):
            self.calls += 1
            return ('{"schema_version":1,"candidate":{"kind":"habit",'
                    '"label":"下午互动习惯","statement":"用户通常在下午聊天。",'
                    '"sources":[{"layer":"l1","id":"l1-a"},'
                    '{"layer":"l1","id":"l1-b"},{"layer":"l1","id":"l1-c"}]}}')

    producer = Producer()
    proposal = PersonaProposalService(producer).preview(
        basis=PersonaBasis.SYSTEM_INFERRED, sources=sources(),
    )
    assert proposal.kind.value == "habit" and len(proposal.source_refs) == 3
    assert producer.calls == 1

    with pytest.raises(PersonaProposalError, match="persona_inference_evidence_threshold_not_met"):
        PersonaProposalService(producer).preview(
            basis=PersonaBasis.SYSTEM_INFERRED, sources=sources()[:2],
        )
    assert producer.calls == 1


def test_preview_rejects_model_source_outside_whitelist_and_unsupported_subset():
    class ForeignProducer:
        def propose(self, *, basis, sources):
            return ('{"schema_version":1,"candidate":{"kind":"preference",'
                    '"label":"越权","statement":"越权来源。",'
                    '"sources":[{"layer":"l1","id":"l1-foreign"}]}}')

    with pytest.raises(PersonaProposalError, match="persona_proposal_schema_invalid"):
        PersonaProposalService(ForeignProducer()).preview(
            basis=PersonaBasis.USER_DECLARED, sources=sources()[:1],
        )

    class ThinProducer:
        def propose(self, *, basis, sources):
            return ('{"schema_version":1,"candidate":{"kind":"habit",'
                    '"label":"证据不足","statement":"用户总在下午聊天。",'
                    '"sources":[{"layer":"l1","id":"l1-a"}]}}')

    with pytest.raises(PersonaProposalError, match="persona_inference_evidence_threshold_not_met"):
        PersonaProposalService(ThinProducer()).preview(
            basis=PersonaBasis.SYSTEM_INFERRED, sources=sources(),
        )


def test_preview_allows_model_to_refuse_without_persisting():
    class Producer:
        def propose(self, *, basis, sources):
            return '{"schema_version":1,"candidate":null}'

    with pytest.raises(PersonaProposalError, match="persona_proposal_no_supported_claim"):
        PersonaProposalService(Producer()).preview(
            basis=PersonaBasis.USER_DECLARED, sources=sources()[:1],
        )
