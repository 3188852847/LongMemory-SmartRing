"""编排 L1/L2 来源到 L3 候选；不调用模型、不注入回答。"""

from datetime import UTC, datetime
from uuid import uuid4

from longmemory.core.common.identifiers import PersonaAuditId, PersonaId, PersonaReviewId
from longmemory.core.memory.l3_persona.contracts import PersonaStore
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaGenerationAudit,
    PersonaKind,
    PersonaMemory,
    PersonaReplacement,
    PersonaReview,
    PersonaReviewDecision,
    PersonaReviewerType,
    PersonaSource,
    PersonaSourceLayer,
    PersonaStatus,
)


class PersonaManagementService:
    def __init__(self, *, persona_store: PersonaStore) -> None:
        self._persona_store = persona_store

    def create_candidate(
        self, *, kind: PersonaKind, basis: PersonaBasis, label: str, statement: str,
        source_refs: tuple[tuple[PersonaSourceLayer, str], ...],
        generator_name: str = "manual_console", generator_version: str = "1",
        valid_from: datetime | None = None, valid_to: datetime | None = None,
        generated_at: datetime | None = None,
        replaces: tuple[PersonaId, ...] = (),
    ) -> PersonaMemory:
        keys = set(source_refs)
        if not source_refs or len(keys) != len(source_refs):
            raise ValueError("persona_sources_invalid")
        resolved = tuple(self._persona_store.resolve_source(layer, source_id)
                         for layer, source_id in source_refs)
        if any(source is None for source in resolved):
            raise ValueError("persona_source_missing_or_inactive")
        subjects = {source.subject_id for source in resolved}
        if len(subjects) != 1:
            raise ValueError("persona_source_subject_mismatch")
        messages = {message for source in resolved for message in source.user_message_ids}
        days = {day for source in resolved for day in source.observation_days}
        if basis == PersonaBasis.USER_DECLARED and not messages:
            raise ValueError("persona_declared_requires_user_l0")
        if basis == PersonaBasis.SYSTEM_INFERRED and (
            len(resolved) < 2 or len(messages) < 3 or len(days) < 2
        ):
            raise ValueError("persona_inference_evidence_threshold_not_met")

        when = generated_at or datetime.now(UTC)
        persona_id = PersonaId(str(uuid4()))
        persona = PersonaMemory(
            persona_id, subjects.pop(), kind, basis, label, statement, when,
            PersonaStatus.CANDIDATE, generator_name, generator_version,
            valid_from, valid_to,
        )
        if len(set(replaces)) != len(replaces):
            raise ValueError("persona_replacements_invalid")
        replacement_targets = []
        for replaced_id in replaces:
            target = self._persona_store.get(replaced_id)
            if target is None or target.status != PersonaStatus.ACTIVE:
                raise ValueError("persona_replacement_target_not_active")
            if target.subject_id != persona.subject_id:
                raise ValueError("persona_replacement_subject_mismatch")
            if target.kind != persona.kind:
                raise ValueError("persona_replacement_kind_mismatch")
            replacement_targets.append(PersonaReplacement(
                persona_id, target.id, target.revision, when,
            ))
        sources = tuple(PersonaSource(
            persona_id, source.source_layer, source.source_id,
            source.content_snapshot, when,
        ) for source in resolved)
        audit = PersonaGenerationAudit(
            PersonaAuditId(str(uuid4())), persona_id, basis,
            generator_name, generator_version, when,
            len(resolved), len(messages), len(days),
        )
        self._persona_store.save_candidate(
            persona, sources, audit, tuple(replacement_targets),
        )
        return persona

    def review(
        self, persona_id: PersonaId, decision: PersonaReviewDecision, *,
        expected_revision: int, reviewed_at: datetime | None = None,
        reviewer_type: PersonaReviewerType = PersonaReviewerType.USER,
        policy_version: str | None = None,
        decision_reason: str | None = None,
    ) -> PersonaMemory:
        review = PersonaReview(
            PersonaReviewId(str(uuid4())), persona_id, decision,
            reviewed_at or datetime.now(UTC), expected_revision,
            reviewer_type, policy_version, decision_reason,
        )
        return self._persona_store.review(review, expected_revision=expected_revision)
