"""显式生成一次 L3 整理建议；模型调用前后都执行证据约束。"""

from longmemory.core.memory.l3_persona.consolidation import (
    PersonaConsolidationProducer,
    PersonaConsolidationSuggestion,
    parse_persona_consolidation,
)
from longmemory.core.memory.l3_persona.models import PersonaBasis, PersonaMemory
from longmemory.core.memory.l3_persona.proposals import PersonaProposalError, PersonaProposalInput

from .proposal_service import PersonaProposalService


class PersonaConsolidationService:
    def __init__(self, producer: PersonaConsolidationProducer) -> None:
        self._producer = producer

    def preview(
        self,
        *,
        basis: PersonaBasis,
        sources: tuple[PersonaProposalInput, ...],
        active_personas: tuple[PersonaMemory, ...],
    ) -> PersonaConsolidationSuggestion:
        """返回不落库建议；NOOP 也是合法且有意义的结果。"""

        PersonaProposalService._validate_evidence(basis, sources)
        try:
            raw = self._producer.propose_consolidation(
                basis=basis, sources=sources, active_personas=active_personas,
            )
        except PersonaProposalError:
            raise
        except Exception:
            raise PersonaProposalError("persona_consolidation_generation_failed") from None
        suggestion = parse_persona_consolidation(
            raw,
            basis=basis,
            allowed_source_refs=tuple(
                (item.source_layer, item.source_id) for item in sources
            ),
            active_personas=active_personas,
        )
        if suggestion.candidate is not None:
            by_key = {(item.source_layer, item.source_id): item for item in sources}
            selected = tuple(by_key[key] for key in suggestion.candidate.source_refs)
            PersonaProposalService._validate_evidence(basis, selected)
        return suggestion
