"""L2→L3 整理从真实 L0 跨日证据到 policy 画像与账本。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_consolidation_run_store import SQLiteConsolidationRunStore
from longmemory.adapters.storage.sqlite_l2_consolidation_source_reader import SQLiteL2ConsolidationSourceReader
from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.application.consolidation.l2_to_l3_service import L2ToL3ConsolidationService
from longmemory.core.memory.consolidation.models import (
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.l3_persona.activation_policy import PersonaRiskAssessment
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 20, 0, tzinfo=UTC)


class Producer:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def propose_consolidation(self, *, basis, sources, active_personas):
        self.calls += 1
        return self.result


def add_active_l2(connection, number):
    moment = NOW - timedelta(days=4 - number)
    scenario_id = f"l2-{number}"
    for suffix in ("a", "b"):
        message_id, memory_id = f"l0-{number}-{suffix}", f"l1-{number}-{suffix}"
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,'user',?,?)",
            (message_id, f"我在下午一点聊天 {number}-{suffix}", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
            "VALUES (?,'user:self',?,?)",
            (memory_id, f"用户在下午一点聊天 {number}-{suffix}。", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
            (memory_id, message_id, moment.isoformat()),
        )
    connection.execute(
        "INSERT INTO scenario_memories VALUES (?,?,?, ?,?,NULL,NULL,'active',?,?,2)",
        (scenario_id, "user:self", "午后聊天", f"第 {number} 天下午一点聊天。",
         moment.isoformat(), "synthetic", "1"),
    )
    connection.executemany(
        "INSERT INTO scenario_memory_sources VALUES (?,?,?,?)",
        ((scenario_id, f"l1-{number}-{suffix}",
          f"用户在下午一点聊天 {number}-{suffix}。", moment.isoformat())
         for suffix in ("a", "b")),
    )


def prepared(tmp_path, producer, count=3):
    connection = open_database(tmp_path / "automatic-l3.db")
    initialize_schema(connection)
    for number in range(1, count + 1):
        add_active_l2(connection, number)
    connection.commit()
    ledger = SQLiteConsolidationRunStore(connection)
    store = SQLitePersonaStore(connection, commit_changes=False)
    service = L2ToL3ConsolidationService(
        run_store=ledger,
        source_reader=SQLiteL2ConsolidationSourceReader(connection),
        consolidation_producer=producer,
        persona_store=store,
        clock=lambda: NOW,
    )
    return connection, ledger, store, service


def run(service):
    return service.run_once(
        subject_id="user:self",
        trigger=ConsolidationTrigger.NEW_EVIDENCE,
        risk=PersonaRiskAssessment(),
        budget_window_start=NOW.replace(hour=0),
        generator_name="model_consolidation_runtime",
        generator_version="l3-persona-consolidation-v1",
    )


def test_cross_day_l2_can_create_policy_audited_persona(tmp_path):
    producer = Producer(
        '{"schema_version":1,"operation":"ADD","candidate":{'
        '"kind":"habit","label":"午后交流习惯",'
        '"statement":"用户经常在下午一点进行交流。","sources":['
        '{"layer":"l2","id":"l2-1"},{"layer":"l2","id":"l2-2"},'
        '{"layer":"l2","id":"l2-3"}]},"replaces":[]}'
    )
    connection, ledger, store, service = prepared(tmp_path, producer)
    result = run(service)
    assert producer.calls == 1
    assert result.run.status == ConsolidationRunStatus.COMPLETED
    assert result.run.outcome_code == "persona_activated"
    assert result.persona is not None and result.persona.status.value == "active"
    review = store.get_review(result.persona.id)
    assert review.reviewer_type.value == "policy"
    assert ledger.latest_cursor("user:self", ConsolidationStage.L2_TO_L3).source_id == "l2-3"
    connection.close()


def test_persona_noop_advances_once_and_does_not_repeat_without_new_l2(tmp_path):
    producer = Producer(
        '{"schema_version":1,"operation":"NOOP","candidate":null,"replaces":[]}'
    )
    connection, ledger, _store, service = prepared(tmp_path, producer)
    first, second = run(service), run(service)
    assert first.run.outcome_code == "persona_noop"
    assert second.run is None and producer.calls == 1
    assert ledger.latest_cursor("user:self", ConsolidationStage.L2_TO_L3).source_id == "l2-3"
    connection.close()
