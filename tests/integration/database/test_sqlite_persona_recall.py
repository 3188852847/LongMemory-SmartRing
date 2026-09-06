"""L3 只读召回只注入相关、当前有效且可追溯的画像。"""

from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_persona_recall import SQLitePersonaRecallProvider
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


def test_recall_returns_related_active_persona_with_source_trace(tmp_path):
    path = tmp_path / "persona-recall.db"
    connection = open_database(path)
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 12, tzinfo=UTC).isoformat()
    connection.execute("INSERT INTO conversation_messages VALUES ('l0','user','我喜欢喝乌龙茶。',?)", (now,))
    connection.execute(
        "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
        "VALUES ('l1','user:self','用户喜欢喝乌龙茶。',?)", (now,),
    )
    connection.execute("INSERT INTO memory_evidence VALUES ('l1','l0','user_stated',?)", (now,))
    connection.commit()
    service = PersonaManagementService(persona_store=SQLitePersonaStore(connection))
    persona = service.create_candidate(
        kind=PersonaKind.PREFERENCE,
        basis=PersonaBasis.USER_DECLARED,
        label="饮品偏好",
        statement="用户明确表示喜欢喝乌龙茶。",
        source_refs=((PersonaSourceLayer.L1, "l1"),),
    )
    service.review(persona.id, PersonaReviewDecision.ACCEPTED, expected_revision=1)
    connection.close()

    provider = SQLitePersonaRecallProvider(path)
    found = provider.recall("我喜欢喝什么茶？")
    missing = provider.recall("我的猫叫什么？")

    assert "乌龙茶" in found.context
    assert found.items[0].persona_id == str(persona.id)
    assert found.items[0].source_refs == (("l1", "l1"),)
    assert found.items[0].source_message_ids == ("l0",)
    assert missing.context == "" and missing.items == ()
