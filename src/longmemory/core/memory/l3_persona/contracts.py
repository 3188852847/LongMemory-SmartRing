"""L3 用户画像的技术中立存储契约。"""

from typing import Protocol

from longmemory.core.common.identifiers import MemorySubjectId, PersonaId
from .models import (
    PersonaGenerationAudit,
    PersonaLifecycleEvent,
    PersonaMemory,
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
    ) -> None: ...

    def get(self, persona_id: PersonaId) -> PersonaMemory | None: ...

    def list_active(self, subject_id: MemorySubjectId) -> tuple[PersonaMemory, ...]: ...

    def list_sources(self, persona_id: PersonaId) -> tuple[PersonaSource, ...]: ...

    def review(
        self, review: PersonaReview, *, expected_revision: int,
    ) -> PersonaMemory: ...

    def list_lifecycle_events(
        self, persona_id: PersonaId,
    ) -> tuple[PersonaLifecycleEvent, ...]: ...
