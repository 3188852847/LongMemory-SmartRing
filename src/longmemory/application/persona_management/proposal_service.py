"""在数据库事务之外生成 L3 草稿，并在调用前后验证证据门槛。"""

from longmemory.core.memory.l3_persona.models import PersonaBasis
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposal,
    PersonaProposalError,
    PersonaProposalInput,
    PersonaProposalProducer,
    parse_persona_proposal,
)


class PersonaProposalService:
    def __init__(self, producer: PersonaProposalProducer) -> None:
        self._producer = producer

    @staticmethod
    def _validate_evidence(
        basis: PersonaBasis, sources: tuple[PersonaProposalInput, ...],
    ) -> None:
        if not 1 <= len(sources) <= 20:
            raise PersonaProposalError("persona_sources_invalid")
        keys = {(item.source_layer, item.source_id) for item in sources}
        if len(keys) != len(sources):
            raise PersonaProposalError("persona_sources_invalid")
        if len({item.subject_id for item in sources}) != 1:
            raise PersonaProposalError("persona_source_subject_mismatch")
        messages = {evidence.message_id for item in sources for evidence in item.user_evidence}
        days = {evidence.observation_day for item in sources for evidence in item.user_evidence}
        if basis == PersonaBasis.USER_DECLARED and not messages:
            raise PersonaProposalError("persona_declared_requires_user_l0")
        if basis == PersonaBasis.SYSTEM_INFERRED and (
            len(sources) < 2 or len(messages) < 3 or len(days) < 2
        ):
            raise PersonaProposalError("persona_inference_evidence_threshold_not_met")

    def preview(
        self, *, basis: PersonaBasis, sources: tuple[PersonaProposalInput, ...],
    ) -> PersonaProposal:
        """生成一次不落库草稿；门槛失败时绝不调用模型。"""

        self._validate_evidence(basis, sources)
        try:
            raw = self._producer.propose(basis=basis, sources=sources)
        except Exception:
            raise PersonaProposalError("persona_proposal_generation_failed") from None
        proposal = parse_persona_proposal(
            raw, basis=basis,
            allowed_source_refs=tuple((item.source_layer, item.source_id) for item in sources),
        )
        if proposal is None:
            raise PersonaProposalError("persona_proposal_no_supported_claim")
        by_key = {(item.source_layer, item.source_id): item for item in sources}
        selected = tuple(by_key[key] for key in proposal.source_refs)
        self._validate_evidence(basis, selected)
        return proposal
