"""L3 用户画像的技术中立存储契约。"""

from typing import Protocol

from longmemory.core.common.identifiers import MemorySubjectId, PersonaId
from .models import (
    PersonaGenerationAudit,
    PersonaLifecycleEvent,
    PersonaMemory,
    PersonaReplacement,
    PersonaResolvedSource,
    PersonaReview,
    PersonaSource,
    PersonaSourceLayer,
)


class PersonaStore(Protocol):
    def resolve_source(
        self, source_layer: PersonaSourceLayer, source_id: str,
    ) -> PersonaResolvedSource | None: ...

    def save_candidate(
        self,
        persona: PersonaMemory,
        sources: tuple[PersonaSource, ...],
        audit: PersonaGenerationAudit,
        replacements: tuple[PersonaReplacement, ...] = (),
    ) -> None: ...

    def get(self, persona_id: PersonaId) -> PersonaMemory | None: ...

    def list_active(self, subject_id: MemorySubjectId) -> tuple[PersonaMemory, ...]: ...

    def list_sources(self, persona_id: PersonaId) -> tuple[PersonaSource, ...]: ...

    def list_replacements(self, persona_id: PersonaId) -> tuple[PersonaReplacement, ...]: ...

    def list_replaced_by(self, persona_id: PersonaId) -> tuple[PersonaReplacement, ...]: ...

    def get_review(self, persona_id: PersonaId) -> PersonaReview | None: ...

    def review(
        self, review: PersonaReview, *, expected_revision: int,
    ) -> PersonaMemory: ...

    def list_lifecycle_events(
        self, persona_id: PersonaId,
    ) -> tuple[PersonaLifecycleEvent, ...]: ...
