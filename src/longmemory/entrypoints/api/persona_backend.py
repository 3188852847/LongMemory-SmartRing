"""L3 用户画像的控制台管理协作者。"""

from datetime import UTC, datetime

from longmemory.adapters.llm.persona_candidate import (
    PERSONA_CONSOLIDATION_PROMPT_VERSION,
    PERSONA_PROMPT_VERSION,
)
from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.application.persona_management.consolidation_service import (
    PersonaConsolidationService,
)
from longmemory.application.persona_management.profile import build_persona_profile
from longmemory.application.persona_management.proposal_service import PersonaProposalService
from longmemory.application.persona_management.service import PersonaManagementService
from longmemory.core.common.identifiers import PersonaId
from longmemory.core.memory.l1_atomic.models import CURRENT_USER_SUBJECT_ID
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaReviewDecision,
    PersonaSourceLayer,
)
from longmemory.core.memory.l3_persona.proposals import (
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
)

from .errors import MemoryAccessError
from .memory_presenters import (
    persona_json,
    persona_model_json,
    persona_replacement_json,
)


class PersonaBackend:
    def __init__(self, *, open_database, allow_management, producer=None, model=None):
        self._open_database = open_database
        self._allow_management = allow_management
        self._producer = producer
        self._model = model

    def list(self, *, state="all", limit=25, offset=0):
        if state not in {"all", "candidate", "active", "rejected", "stale"}:
            raise MemoryAccessError("persona_filter_invalid", 400)
        with self._open_database() as connection:
            where, parameters = ("", []) if state == "all" else (" WHERE status=?", [state])
            total = connection.execute(
                "SELECT count(*) FROM persona_memories" + where, parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM persona_memories" + where
                + " ORDER BY generated_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return {
                "items": [persona_json(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def profile(self):
        """构造一份聚合用户画像；底层原子断言和来源链保持不变。"""

        with self._open_database() as connection:
            store = SQLitePersonaStore(connection)
            profile = build_persona_profile(
                CURRENT_USER_SUBJECT_ID,
                store.list_active(CURRENT_USER_SUBJECT_ID),
            )
            counts = {status: 0 for status in ("candidate", "active", "rejected", "stale")}
            for row in connection.execute(
                "SELECT status, count(*) AS amount FROM persona_memories "
                "WHERE subject_id=? GROUP BY status",
                (str(CURRENT_USER_SUBJECT_ID),),
            ).fetchall():
                counts[row["status"]] = row["amount"]
            return {
                "subject_id": str(profile.subject_id),
                "representation": "aggregated_active_assertions_v1",
                "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
                "active_assertion_count": profile.assertion_count,
                "status_counts": counts,
                "sections": [{
                    "kind": section.kind.value,
                    "items": [persona_model_json(item) for item in section.assertions],
                } for section in profile.sections],
            }

    def list_source_options(self):
        """只返回当前有效的 L1 和已接受 L2；不自动判断适合哪个画像。"""

        with self._open_database() as connection:
            l1_rows = connection.execute(
                "SELECT id, subject_id, content, recorded_at FROM atomic_memories "
                "WHERE retired_at IS NULL ORDER BY recorded_at DESC, id DESC LIMIT 100"
            ).fetchall()
            l2_rows = connection.execute(
                "SELECT id, subject_id, title, summary, generated_at FROM scenario_memories "
                "WHERE status='active' ORDER BY generated_at DESC, id DESC LIMIT 100"
            ).fetchall()
            return {
                "l1": [{"layer": "l1", "id": row["id"], "subject_id": row["subject_id"],
                        "content": row["content"], "recorded_at": row["recorded_at"]}
                       for row in l1_rows],
                "l2": [{"layer": "l2", "id": row["id"], "subject_id": row["subject_id"],
                        "content": f'{row["title"]}：{row["summary"]}',
                        "recorded_at": row["generated_at"]} for row in l2_rows],
                "selection_is_semantic": False,
            }

    def get(self, persona_id):
        with self._open_database() as connection:
            store = SQLitePersonaStore(connection)
            identity = PersonaId(persona_id)
            persona = store.get(identity)
            if persona is None:
                raise MemoryAccessError("persona_not_found", 404)
            data = persona_model_json(persona)
            audit = connection.execute(
                "SELECT source_count, source_message_count, observation_day_count "
                "FROM persona_generation_audits WHERE persona_id=?", (persona_id,),
            ).fetchone()
            data["audit"] = dict(audit) if audit is not None else None
            sources = []
            for source in store.list_sources(identity):
                resolved = store.resolve_source(source.source_layer, source.source_id)
                if source.source_layer == PersonaSourceLayer.L1:
                    query = (
                        "SELECT m.id, m.content, m.created_at, e.source_type FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at, m.id"
                    )
                else:
                    query = (
                        "SELECT DISTINCT m.id, m.content, m.created_at, e.source_type "
                        "FROM scenario_memory_sources s JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at, m.id"
                    )
                messages = [dict(row) for row in connection.execute(
                    query, (source.source_id,),
                ).fetchall()]
                sources.append({
                    "source_layer": source.source_layer.value,
                    "source_id": source.source_id,
                    "source_content_snapshot": source.source_content_snapshot,
                    "linked_at": source.linked_at.isoformat(),
                    "current_content": resolved.content_snapshot if resolved else None,
                    "active": resolved is not None,
                    "l0_sources": messages,
                })
            data["sources"] = sources
            data["replaces"] = [persona_replacement_json(
                replacement, store.get(replacement.replaced_persona_id),
            ) for replacement in store.list_replacements(identity)]
            data["replaced_by"] = [persona_replacement_json(
                replacement, store.get(replacement.candidate_persona_id),
            ) for replacement in store.list_replaced_by(identity)]
            review = store.get_review(identity)
            data["review"] = None if review is None else {
                "decision": review.decision.value,
                "reviewer_type": review.reviewer_type.value,
                "reviewed_at": review.reviewed_at.isoformat(),
                "persona_revision": review.persona_revision,
                "policy_version": review.policy_version,
                "decision_reason": review.decision_reason,
            }
            data["lifecycle_events"] = [{
                "id": str(event.id), "action": event.action.value,
                "source_layer": event.source_layer.value, "source_id": event.source_id,
                "occurred_at": event.occurred_at.isoformat(),
                "previous_status": event.previous_status.value,
                "new_status": event.new_status.value,
                "persona_revision": event.persona_revision,
            } for event in store.list_lifecycle_events(identity)]
            return data

    def create(self, *, kind, basis, label, statement, sources, valid_from=None,
               valid_to=None, creation_kind="manual", replaces=()):
        with self._open_database(write_capability="persona") as connection:
            service = PersonaManagementService(
                persona_store=SQLitePersonaStore(connection, commit_changes=False),
            )
            try:
                try:
                    parsed_valid_from = datetime.fromisoformat(valid_from) if valid_from else None
                    parsed_valid_to = datetime.fromisoformat(valid_to) if valid_to else None
                except ValueError:
                    raise MemoryAccessError("persona_valid_time_invalid", 400) from None
                model_generated = creation_kind in {"model_assisted", "model_consolidation"}
                if model_generated and self._producer is None:
                    raise MemoryAccessError("persona_model_preview_unavailable", 503)
                persona = service.create_candidate(
                    kind=PersonaKind(kind), basis=PersonaBasis(basis), label=label,
                    statement=statement,
                    source_refs=tuple((PersonaSourceLayer(item["layer"]), item["id"])
                                      for item in sources),
                    generator_name=("model_assisted_console" if model_generated
                                    else "manual_console"),
                    generator_version=(
                        PERSONA_CONSOLIDATION_PROMPT_VERSION
                        if creation_kind == "model_consolidation"
                        else PERSONA_PROMPT_VERSION if creation_kind == "model_assisted"
                        else "1"
                    ),
                    valid_from=parsed_valid_from,
                    valid_to=parsed_valid_to,
                    replaces=tuple(PersonaId(item) for item in replaces),
                )
            except (ValueError, LookupError) as error:
                raise MemoryAccessError(str(error), 400) from None
            connection.commit()
            return {"created": True, "id": str(persona.id), "status": persona.status.value}

    def preview(self, *, basis, sources):
        parsed_basis, inputs, _active = self._load_preview_inputs(basis, sources)
        try:
            proposal = PersonaProposalService(self._producer).preview(
                basis=parsed_basis, sources=tuple(inputs),
            )
        except PersonaProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        return {
            "kind": proposal.kind.value,
            "basis": proposal.basis.value,
            "label": proposal.label,
            "statement": proposal.statement,
            "sources": [{"layer": layer.value, "id": source_id}
                        for layer, source_id in proposal.source_refs],
            "generator_name": "model_assisted_console",
            "generator_version": PERSONA_PROMPT_VERSION,
            "model": self._model,
            "persisted": False,
        }

    def preview_consolidation(self, *, basis, sources):
        parsed_basis, inputs, active_personas = self._load_preview_inputs(
            basis, sources, include_active=True,
        )
        try:
            suggestion = PersonaConsolidationService(self._producer).preview(
                basis=parsed_basis,
                sources=tuple(inputs),
                active_personas=active_personas,
            )
        except PersonaProposalError as error:
            raise MemoryAccessError(str(error), 400) from None
        candidate = suggestion.candidate
        return {
            "operation": suggestion.operation.value,
            "candidate": None if candidate is None else {
                "kind": candidate.kind.value,
                "basis": candidate.basis.value,
                "label": candidate.label,
                "statement": candidate.statement,
                "sources": [{"layer": layer.value, "id": source_id}
                            for layer, source_id in candidate.source_refs],
            },
            "replaces": [str(item) for item in suggestion.replaces],
            "generator_name": "model_assisted_console",
            "generator_version": PERSONA_CONSOLIDATION_PROMPT_VERSION,
            "model": self._model,
            "persisted": False,
        }

    def review(self, persona_id, *, decision, expected_revision):
        with self._open_database(write_capability="persona") as connection:
            service = PersonaManagementService(
                persona_store=SQLitePersonaStore(connection, commit_changes=False),
            )
            try:
                persona = service.review(
                    PersonaId(persona_id), PersonaReviewDecision(decision),
                    expected_revision=expected_revision,
                )
            except ValueError as error:
                raise MemoryAccessError(str(error), 409) from None
            connection.commit()
            return {
                "reviewed": True,
                "id": persona_id,
                "status": persona.status.value,
                "revision": persona.revision,
            }

    def _load_preview_inputs(self, basis, sources, *, include_active=False):
        if not self._allow_management:
            raise MemoryAccessError("persona_management_disabled", 403)
        if self._producer is None:
            raise MemoryAccessError("persona_model_preview_unavailable", 503)
        try:
            parsed_basis = PersonaBasis(basis)
        except ValueError:
            raise MemoryAccessError("persona_basis_invalid", 400) from None
        inputs = []
        with self._open_database() as connection:
            store = SQLitePersonaStore(connection)
            active_personas = (
                store.list_active(CURRENT_USER_SUBJECT_ID) if include_active else ()
            )
            for item in sources:
                layer = PersonaSourceLayer(item["layer"])
                resolved = store.resolve_source(layer, item["id"])
                if resolved is None:
                    raise MemoryAccessError("persona_source_missing_or_inactive", 400)
                if layer == PersonaSourceLayer.L1:
                    query = (
                        "SELECT m.id,m.content,m.created_at FROM memory_evidence e "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE e.memory_id=? AND m.role='user' ORDER BY m.created_at,m.id"
                    )
                else:
                    query = (
                        "SELECT DISTINCT m.id,m.content,m.created_at FROM scenario_memory_sources s "
                        "JOIN memory_evidence e ON e.memory_id=s.memory_id "
                        "JOIN conversation_messages m ON m.id=e.source_message_id "
                        "WHERE s.scenario_id=? AND m.role='user' ORDER BY m.created_at,m.id"
                    )
                rows = connection.execute(query, (item["id"],)).fetchall()
                inputs.append(PersonaProposalInput(
                    layer,
                    item["id"],
                    resolved.subject_id,
                    resolved.content_snapshot,
                    tuple(PersonaProposalEvidence(
                        row["id"], row["content"],
                        datetime.fromisoformat(row["created_at"])
                        .astimezone(UTC).date().isoformat(),
                    ) for row in rows),
                ))
        return parsed_basis, inputs, active_personas
