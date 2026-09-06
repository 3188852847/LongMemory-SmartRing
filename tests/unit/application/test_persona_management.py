"""L3 候选必须有足量、可追溯且跨日的用户证据。"""

from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.application.persona_management.service import PersonaManagementService
from longmemory.core.memory.l3_persona.models import (
    PersonaBasis,
    PersonaKind,
    PersonaReviewDecision,
    PersonaSourceLayer,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


def prepared(tmp_path):
    connection = open_database(tmp_path / "persona.db")
    initialize_schema(connection)
    rows = [
        ("l0-a", "我一般下午找你聊天。", "2026-09-05T05:00:00+00:00", "l1-a", "用户一般下午聊天。"),
        ("l0-b", "今天下午我又来了。", "2026-09-06T05:10:00+00:00", "l1-b", "用户今天下午聊天。"),
        ("l0-c", "下午聊一会让我比较放松。", "2026-09-06T05:20:00+00:00", "l1-c", "用户认为下午聊天有助于放松。"),
    ]
    for message_id, text, created_at, memory_id, content in rows:
        connection.execute("INSERT INTO conversation_messages VALUES (?, 'user', ?, ?)", (message_id,text,created_at))
        connection.execute("INSERT INTO atomic_memories (id,subject_id,content,recorded_at) VALUES (?,'user:self',?,?)", (memory_id,content,created_at))
        connection.execute("INSERT INTO memory_evidence VALUES (?,?, 'user_stated', ?)", (memory_id,message_id,created_at))
    connection.commit()
    return connection


def test_declared_and_inferred_persona_require_different_evidence(tmp_path):
    connection = prepared(tmp_path)
    service = PersonaManagementService(persona_store=SQLitePersonaStore(connection))
    declared = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="下午聊天", statement="用户明确表示一般在下午聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-a"),),
    )
    assert declared.status.value == "candidate"

    with pytest.raises(ValueError, match="persona_inference_evidence_threshold_not_met"):
        service.create_candidate(
            kind=PersonaKind.HABIT, basis=PersonaBasis.SYSTEM_INFERRED,
            label="下午互动习惯", statement="用户通常在下午进行陪伴对话。",
            source_refs=((PersonaSourceLayer.L1,"l1-a"),(PersonaSourceLayer.L1,"l1-b")),
        )

    inferred = service.create_candidate(
        kind=PersonaKind.HABIT, basis=PersonaBasis.SYSTEM_INFERRED,
        label="下午互动习惯", statement="用户通常在下午进行陪伴对话。",
        source_refs=tuple((PersonaSourceLayer.L1,f"l1-{name}") for name in "abc"),
    )
    audit = connection.execute(
        "SELECT source_count,source_message_count,observation_day_count "
        "FROM persona_generation_audits WHERE persona_id=?", (str(inferred.id),),
    ).fetchone()
    assert tuple(audit) == (3,3,2)
    reviewed = service.review(inferred.id, PersonaReviewDecision.ACCEPTED, expected_revision=1)
    assert reviewed.status.value == "active" and reviewed.revision == 2
    connection.close()


def test_l1_source_retirement_stales_persona_with_audit_event(tmp_path):
    connection = prepared(tmp_path)
    service = PersonaManagementService(persona_store=SQLitePersonaStore(connection))
    persona = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="下午聊天", statement="用户明确表示一般在下午聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-a"),),
    )
    connection.execute("UPDATE atomic_memories SET retired_at=? WHERE id='l1-a'", (datetime.now(UTC).isoformat(),))
    row = connection.execute("SELECT status,revision FROM persona_memories WHERE id=?", (str(persona.id),)).fetchone()
    event = connection.execute("SELECT action,source_layer,source_id FROM persona_lifecycle_events WHERE persona_id=?", (str(persona.id),)).fetchone()
    assert tuple(row) == ("stale",2)
    assert tuple(event) == ("source_retired","l1","l1-a")
    connection.close()
