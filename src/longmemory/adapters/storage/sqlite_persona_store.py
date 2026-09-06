"""L3 用户画像的 SQLite 事务存储与来源资格解析。"""

from datetime import UTC, datetime
from sqlite3 import Connection, Row

from longmemory.core.common.identifiers import (
    MemorySubjectId,
    PersonaId,
    PersonaLifecycleEventId,
)
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaGenerationAudit,
    PersonaKind,
    PersonaLifecycleAction,
    PersonaLifecycleEvent,
    PersonaMemory,
    PersonaReplacement,
    PersonaResolvedSource,
    PersonaReview,
    PersonaReviewDecision,
    PersonaSource,
    PersonaSourceLayer,
    PersonaStatus,
)


class SQLitePersonaStore:
    def __init__(self, connection: Connection, *, commit_changes: bool = True) -> None:
        self._connection = connection
        self._commit_changes = commit_changes

    def resolve_source(
        self, source_layer: PersonaSourceLayer, source_id: str,
    ) -> PersonaResolvedSource | None:
        """仅接受当前有效来源，并将 L2 继续向下解析到用户 L0。"""

        if source_layer == PersonaSourceLayer.L1:
            row = self._connection.execute(
                "SELECT id, subject_id, content FROM atomic_memories "
                "WHERE id=? AND retired_at IS NULL", (source_id,),
            ).fetchone()
            if row is None:
                return None
            messages = self._connection.execute(
                "SELECT DISTINCT m.id, m.created_at FROM memory_evidence e "
                "JOIN conversation_messages m ON m.id=e.source_message_id "
                "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                (source_id,),
            ).fetchall()
            snapshot = row["content"]
        else:
            row = self._connection.execute(
                "SELECT id, subject_id, title, summary FROM scenario_memories "
                "WHERE id=? AND status='active'", (source_id,),
            ).fetchone()
            if row is None:
                return None
            messages = self._connection.execute(
                "SELECT DISTINCT m.id, m.created_at FROM scenario_memory_sources s "
                "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                "JOIN conversation_messages m ON m.id=e.source_message_id "
                "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at, m.id",
                (source_id,),
            ).fetchall()
            snapshot = f'{row["title"]}：{row["summary"]}'
        days = tuple(sorted({
            datetime.fromisoformat(message["created_at"]).astimezone(UTC).date().isoformat()
            for message in messages
        }))
        return PersonaResolvedSource(
            source_layer, source_id, MemorySubjectId(row["subject_id"]), snapshot,
            tuple(message["id"] for message in messages), days,
        )

    def save_candidate(
        self,
        persona: PersonaMemory,
        sources: tuple[PersonaSource, ...],
        audit: PersonaGenerationAudit,
        replacements: tuple[PersonaReplacement, ...] = (),
    ) -> None:
        """原子保存画像、来源快照与审计统计。"""

        if persona.status != PersonaStatus.CANDIDATE:
            raise ValueError("persona_must_start_as_candidate")
        keys = {(source.source_layer, source.source_id) for source in sources}
        if len(keys) != len(sources) or not sources:
            raise ValueError("persona_sources_invalid")
        if audit.persona_id != persona.id or any(source.persona_id != persona.id for source in sources):
            raise ValueError("persona_relation_mismatch")
        if (audit.basis != persona.basis
                or audit.generator_name != persona.generator_name
                or audit.generator_version != persona.generator_version
                or audit.generated_at != persona.generated_at
                or audit.source_count != len(sources)):
            raise ValueError("persona_audit_mismatch")
        if any(item.candidate_persona_id != persona.id for item in replacements):
            raise ValueError("persona_replacement_candidate_mismatch")
        if len({item.replaced_persona_id for item in replacements}) != len(replacements):
            raise ValueError("persona_replacements_invalid")
        for item in replacements:
            target = self.get(item.replaced_persona_id)
            if target is None or target.status != PersonaStatus.ACTIVE:
                raise ValueError("persona_replacement_target_not_active")
            if target.subject_id != persona.subject_id:
                raise ValueError("persona_replacement_subject_mismatch")
            if target.kind != persona.kind:
                raise ValueError("persona_replacement_kind_mismatch")
            if target.revision != item.target_revision:
                raise ValueError("persona_replacement_revision_mismatch")
        resolved = tuple(
            self.resolve_source(source.source_layer, source.source_id)
            for source in sources
        )
        if any(item is None for item in resolved):
            raise ValueError("persona_source_missing_or_inactive")
        if any(item.subject_id != persona.subject_id for item in resolved):
            raise ValueError("persona_source_subject_mismatch")
        if any(item.content_snapshot != source.source_content_snapshot
               for item, source in zip(resolved, sources, strict=True)):
            raise ValueError("persona_source_snapshot_mismatch")
        messages = {message for item in resolved for message in item.user_message_ids}
        days = {day for item in resolved for day in item.observation_days}
        if (audit.source_message_count != len(messages)
                or audit.observation_day_count != len(days)):
            raise ValueError("persona_audit_mismatch")

        try:
            self._connection.execute(
                "INSERT INTO persona_memories "
                "(id,subject_id,kind,basis,label,statement,generated_at,valid_from,"
                "valid_to,status,generator_name,generator_version,revision) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(persona.id), str(persona.subject_id), persona.kind.value,
                    persona.basis.value, persona.label.strip(), persona.statement.strip(),
                    persona.generated_at.isoformat(), self._time(persona.valid_from),
                    self._time(persona.valid_to), persona.status.value,
                    persona.generator_name, persona.generator_version, persona.revision,
                ),
            )
            self._connection.executemany(
                "INSERT INTO persona_sources "
                "(persona_id,source_layer,source_id,source_content_snapshot,linked_at) "
                "VALUES (?,?,?,?,?)",
                tuple((str(item.persona_id), item.source_layer.value, item.source_id,
                       item.source_content_snapshot, item.linked_at.isoformat()) for item in sources),
            )
            self._connection.execute(
                "INSERT INTO persona_generation_audits "
                "(id,persona_id,basis,generator_name,generator_version,generated_at,"
                "source_count,source_message_count,observation_day_count) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(audit.id), str(audit.persona_id), audit.basis.value,
                    audit.generator_name, audit.generator_version,
                    audit.generated_at.isoformat(), audit.source_count,
                    audit.source_message_count, audit.observation_day_count,
                ),
            )
            self._connection.executemany(
                "INSERT INTO persona_replacements "
                "(candidate_persona_id,replaced_persona_id,target_revision,linked_at,applied_at) "
                "VALUES (?,?,?,?,NULL)",
                tuple((str(item.candidate_persona_id), str(item.replaced_persona_id),
                       item.target_revision, item.linked_at.isoformat()) for item in replacements),
            )
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def get(self, persona_id: PersonaId) -> PersonaMemory | None:
        row = self._connection.execute(
            "SELECT * FROM persona_memories WHERE id=?", (str(persona_id),),
        ).fetchone()
        return None if row is None else self._row_to_persona(row)

    def list_active(self, subject_id: MemorySubjectId) -> tuple[PersonaMemory, ...]:
        """返回构成当前统一画像的已接受断言，不包含候选和失效历史。"""

        rows = self._connection.execute(
            "SELECT * FROM persona_memories "
            "WHERE subject_id=? AND status='active' "
            "ORDER BY generated_at DESC, id DESC",
            (str(subject_id),),
        ).fetchall()
        return tuple(self._row_to_persona(row) for row in rows)

    def list_sources(self, persona_id: PersonaId) -> tuple[PersonaSource, ...]:
        rows = self._connection.execute(
            "SELECT * FROM persona_sources WHERE persona_id=? "
            "ORDER BY linked_at, source_layer, source_id", (str(persona_id),),
        ).fetchall()
        return tuple(PersonaSource(
            PersonaId(row["persona_id"]), PersonaSourceLayer(row["source_layer"]),
            row["source_id"], row["source_content_snapshot"],
            datetime.fromisoformat(row["linked_at"]),
        ) for row in rows)

    def list_replacements(self, persona_id: PersonaId) -> tuple[PersonaReplacement, ...]:
        rows = self._connection.execute(
            "SELECT * FROM persona_replacements WHERE candidate_persona_id=? "
            "ORDER BY linked_at,replaced_persona_id", (str(persona_id),),
        ).fetchall()
        return tuple(self._row_to_replacement(row) for row in rows)

    def list_replaced_by(self, persona_id: PersonaId) -> tuple[PersonaReplacement, ...]:
        rows = self._connection.execute(
            "SELECT * FROM persona_replacements "
            "WHERE replaced_persona_id=? AND applied_at IS NOT NULL "
            "ORDER BY applied_at,candidate_persona_id", (str(persona_id),),
        ).fetchall()
        return tuple(self._row_to_replacement(row) for row in rows)

    def review(self, review: PersonaReview, *, expected_revision: int) -> PersonaMemory:
        if review.persona_revision != expected_revision:
            raise ValueError("persona_review_revision_mismatch")
        status = PersonaStatus.ACTIVE if review.decision == PersonaReviewDecision.ACCEPTED else PersonaStatus.REJECTED
        try:
            replacements = self.list_replacements(review.persona_id)
            persona = self.get(review.persona_id)
            if persona is None:
                raise ValueError("persona_review_conflict")
            if review.decision == PersonaReviewDecision.ACCEPTED:
                for replacement in replacements:
                    target = self.get(replacement.replaced_persona_id)
                    if (target is None or target.status != PersonaStatus.ACTIVE
                            or target.revision != replacement.target_revision
                            or target.subject_id != persona.subject_id
                            or target.kind != persona.kind):
                        raise ValueError("persona_replacement_conflict")
            cursor = self._connection.execute(
                "UPDATE persona_memories SET status=?, revision=revision+1 "
                "WHERE id=? AND status='candidate' AND revision=?",
                (status.value, str(review.persona_id), expected_revision),
            )
            if cursor.rowcount != 1:
                raise ValueError("persona_review_conflict")
            self._connection.execute(
                "INSERT INTO persona_reviews "
                "(id,persona_id,decision,reviewer_type,reviewed_at,persona_revision) "
                "VALUES (?, ?, ?, 'user', ?, ?)",
                (str(review.id), str(review.persona_id), review.decision.value,
                 review.reviewed_at.isoformat(), review.persona_revision),
            )
            if review.decision == PersonaReviewDecision.ACCEPTED:
                for replacement in replacements:
                    cursor = self._connection.execute(
                        "UPDATE persona_memories SET status='stale',revision=revision+1 "
                        "WHERE id=? AND status='active' AND revision=?",
                        (str(replacement.replaced_persona_id), replacement.target_revision),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("persona_replacement_conflict")
                self._connection.execute(
                    "UPDATE persona_replacements SET applied_at=? "
                    "WHERE candidate_persona_id=?",
                    (review.reviewed_at.isoformat(), str(review.persona_id)),
                )
            if self._commit_changes:
                self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        updated = self.get(review.persona_id)
        if updated is None:
            raise RuntimeError("persona_missing_after_review")
        return updated

    def list_lifecycle_events(self, persona_id: PersonaId) -> tuple[PersonaLifecycleEvent, ...]:
        rows = self._connection.execute(
            "SELECT * FROM persona_lifecycle_events WHERE persona_id=? "
            "ORDER BY occurred_at, id", (str(persona_id),),
        ).fetchall()
        return tuple(PersonaLifecycleEvent(
            PersonaLifecycleEventId(row["id"]), PersonaId(row["persona_id"]),
            PersonaLifecycleAction(row["action"]), PersonaSourceLayer(row["source_layer"]),
            row["source_id"], datetime.fromisoformat(row["occurred_at"]),
            PersonaStatus(row["previous_status"]), PersonaStatus(row["new_status"]),
            row["persona_revision"],
        ) for row in rows)

    @staticmethod
    def _time(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _row_to_persona(row: Row) -> PersonaMemory:
        return PersonaMemory(
            PersonaId(row["id"]), MemorySubjectId(row["subject_id"]),
            PersonaKind(row["kind"]), PersonaBasis(row["basis"]),
            row["label"], row["statement"], datetime.fromisoformat(row["generated_at"]),
            PersonaStatus(row["status"]), row["generator_name"], row["generator_version"],
            datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
            datetime.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
            row["revision"],
        )

    @staticmethod
    def _row_to_replacement(row: Row) -> PersonaReplacement:
        return PersonaReplacement(
            PersonaId(row["candidate_persona_id"]), PersonaId(row["replaced_persona_id"]),
            row["target_revision"], datetime.fromisoformat(row["linked_at"]),
            datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None,
        )
