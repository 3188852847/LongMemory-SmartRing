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


def test_accepting_replacement_activates_new_and_stales_old_atomically(tmp_path):
    connection = prepared(tmp_path)
    store = SQLitePersonaStore(connection)
    service = PersonaManagementService(persona_store=store)
    old = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="下午聊天", statement="用户偏好下午聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-a"),),
    )
    old = service.review(old.id, PersonaReviewDecision.ACCEPTED, expected_revision=1)
    replacement = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="傍晚聊天", statement="用户现在更偏好傍晚聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-b"),), replaces=(old.id,),
    )

    assert store.get(old.id).status.value == "active"
    assert store.list_replacements(replacement.id)[0].applied_at is None
    replacement = service.review(
        replacement.id, PersonaReviewDecision.ACCEPTED, expected_revision=1,
    )

    assert replacement.status.value == "active"
    assert store.get(old.id).status.value == "stale"
    assert store.get(old.id).revision == 3
    assert store.list_replacements(replacement.id)[0].applied_at is not None
    assert store.list_replaced_by(old.id)[0].candidate_persona_id == replacement.id
    assert tuple(item.id for item in store.list_active(old.subject_id)) == (replacement.id,)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_rejected_replacement_does_not_change_old_persona(tmp_path):
    connection = prepared(tmp_path)
    store = SQLitePersonaStore(connection)
    service = PersonaManagementService(persona_store=store)
    old = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="下午聊天", statement="用户偏好下午聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-a"),),
    )
    old = service.review(old.id, PersonaReviewDecision.ACCEPTED, expected_revision=1)
    replacement = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="候选变化", statement="这条变化不应被接受。",
        source_refs=((PersonaSourceLayer.L1,"l1-b"),), replaces=(old.id,),
    )
    service.review(replacement.id, PersonaReviewDecision.REJECTED, expected_revision=1)

    assert store.get(old.id).status.value == "active"
    assert store.list_replacements(replacement.id)[0].applied_at is None
    assert store.list_replaced_by(old.id) == ()
    connection.close()


def test_accepting_replacement_rolls_back_when_target_changed(tmp_path):
    connection = prepared(tmp_path)
    store = SQLitePersonaStore(connection)
    service = PersonaManagementService(persona_store=store)
    old = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="下午聊天", statement="用户偏好下午聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-a"),),
    )
    old = service.review(old.id, PersonaReviewDecision.ACCEPTED, expected_revision=1)
    replacement = service.create_candidate(
        kind=PersonaKind.PREFERENCE, basis=PersonaBasis.USER_DECLARED,
        label="傍晚聊天", statement="用户现在更偏好傍晚聊天。",
        source_refs=((PersonaSourceLayer.L1,"l1-b"),), replaces=(old.id,),
    )

    # 模拟候选创建后，另一个入口先改变了旧画像。接受时必须检测到
    # revision 不再匹配，并让“新画像激活 + 旧画像失效”整笔事务回滚。
    connection.execute(
        "UPDATE persona_memories SET revision=revision+1 WHERE id=?", (str(old.id),),
    )
    connection.commit()

    with pytest.raises(ValueError, match="persona_replacement_conflict"):
        service.review(
            replacement.id, PersonaReviewDecision.ACCEPTED, expected_revision=1,
        )

    assert store.get(replacement.id).status.value == "candidate"
    assert store.get(replacement.id).revision == 1
    assert store.get(old.id).status.value == "active"
    assert store.get(old.id).revision == 3
    assert store.list_replacements(replacement.id)[0].applied_at is None
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
