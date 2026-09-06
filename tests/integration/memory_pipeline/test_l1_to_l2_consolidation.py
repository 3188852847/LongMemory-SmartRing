"""L1→L2 整理的成功、NOOP、失败和游标闭环。"""

from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.adapters.storage.sqlite_l1_consolidation_source_reader import (
    SQLiteL1ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.application.consolidation.l1_to_l2_service import (
    L1ToL2ConsolidationService,
)
from longmemory.core.memory.consolidation.models import (
    ConsolidationRunStatus,
    ConsolidationStage,
    ConsolidationTrigger,
)
from longmemory.core.memory.consolidation.risk_review import (
    ConsolidationRiskReview,
    ConsolidationRiskReviewError,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 20, 0, tzinfo=UTC)


class Producer:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def propose(self, *, sources):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class Reviewer:
    version = "synthetic-risk-v1"

    def __init__(self, *, ready=True, sensitive=False, conflict=False, error=False):
        self.ready = ready
        self.sensitive = sensitive
        self.conflict = conflict
        self.error = error
        self.calls = 0

    def review(self, value):
        self.calls += 1
        if self.error:
            raise ConsolidationRiskReviewError("synthetic_risk_failure")
        return ConsolidationRiskReview(
            sensitive=self.sensitive,
            unresolved_conflict=self.conflict,
            clarification_allowed=True,
            reason_codes=(),
            reviewer_version=self.version,
        )


def prepared(tmp_path, producer, reviewer=None):
    connection = open_database(tmp_path / "automatic-l2.db")
    initialize_schema(connection)
    for number in range(1, 5):
        moment = NOW - timedelta(days=4 - number)
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,'user',?,?)",
            (f"l0-{number}", f"答辩原话 {number}", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO atomic_memories (id,subject_id,content,recorded_at) "
            "VALUES (?,'user:self',?,?)",
            (f"l1-{number}", f"用户正在准备答辩 {number}。", moment.isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
            (f"l1-{number}", f"l0-{number}", moment.isoformat()),
        )
    connection.commit()
    ledger = SQLiteConsolidationRunStore(connection)
    service = L1ToL2ConsolidationService(
        run_store=ledger,
        source_reader=SQLiteL1ConsolidationSourceReader(connection),
        proposal_producer=producer,
        risk_reviewer=reviewer or Reviewer(),
        memory_store=SQLiteMemoryStore(connection, commit_changes=False),
        scenario_store=SQLiteScenarioStore(connection, commit_changes=False),
        clock=lambda: NOW,
    )
    return connection, ledger, service


def run(service):
    return service.run_once(
        subject_id="user:self",
        trigger=ConsolidationTrigger.NEW_EVIDENCE,
        budget_window_start=NOW.replace(hour=0),
        generator_name="model_consolidation_runtime",
        generator_version="l2-scenario-preview-v2",
    )


def test_model_candidate_can_be_policy_activated_and_advance_cursor(tmp_path):
    producer = Producer(
        '{"schema_version":2,"candidate":{"title":"准备答辩",'
        '"summary":"用户最近持续准备答辩。",'
        '"source_memory_ids":["l1-1","l1-2","l1-3"]}}'
    )
    connection, ledger, service = prepared(tmp_path, producer)
    result = run(service)
    assert producer.calls == 1
    assert result.run.status == ConsolidationRunStatus.COMPLETED
    assert result.run.outcome_code == "scenario_activated"
    assert result.run.model_call_count == 2
    assert result.risk_review.reviewer_version == "synthetic-risk-v1"
    assert result.scenario is not None and result.scenario.status.value == "active"
    assert ledger.latest_cursor("user:self", ConsolidationStage.L1_TO_L2).source_id == "l1-4"
    review = connection.execute(
        "SELECT reviewer_type,policy_version FROM scenario_reviews"
    ).fetchone()
    assert tuple(review) == ("policy", "scenario-activation-v1")
    connection.close()


def test_model_noop_is_completed_once_and_does_not_repeat_without_new_l1(tmp_path):
    producer = Producer('{"schema_version":2,"candidate":null}')
    connection, ledger, service = prepared(tmp_path, producer)
    first = run(service)
    second = run(service)
    assert first.run.outcome_code == "no_coherent_group"
    assert second.run is None
    assert producer.calls == 1
    assert ledger.latest_cursor("user:self", ConsolidationStage.L1_TO_L2).source_id == "l1-4"
    connection.close()


def test_model_failure_is_recorded_without_cursor_or_retry(tmp_path):
    producer = Producer(error=OSError("synthetic network failure"))
    connection, ledger, service = prepared(tmp_path, producer)
    result = run(service)
    assert producer.calls == 1
    assert result.run.status == ConsolidationRunStatus.FAILED
    assert result.run.outcome_code == "scenario_proposal_generation_failed"
    assert ledger.latest_cursor("user:self", ConsolidationStage.L1_TO_L2) is None
    connection.close()


def test_policy_block_is_completed_but_never_persists_scenario(tmp_path):
    producer = Producer(
        '{"schema_version":2,"candidate":{"title":"敏感",'
        '"summary":"不应自动生效。",'
        '"source_memory_ids":["l1-1","l1-2","l1-3"]}}'
    )
    connection, _ledger, service = prepared(
        tmp_path, producer, Reviewer(sensitive=True),
    )
    result = run(service)
    assert result.run.outcome_code == "scenario_sensitive_content"
    assert result.scenario is None
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    connection.close()


def test_incomplete_risk_check_does_not_call_model_or_advance_cursor(tmp_path):
    producer = Producer(
        '{"schema_version":2,"candidate":{"title":"不应调用",'
        '"summary":"不应调用。","source_memory_ids":["l1-1","l1-2","l1-3"]}}'
    )
    reviewer = Reviewer(ready=False)
    connection, ledger, service = prepared(tmp_path, producer, reviewer)
    result = run(service)
    assert result.run is None
    assert result.trigger_decision.reason.value == "risk_assessment_incomplete"
    assert producer.calls == 0
    assert reviewer.calls == 0
    assert ledger.latest_cursor("user:self", ConsolidationStage.L1_TO_L2) is None
    connection.close()


def test_risk_review_failure_is_recorded_without_activation_or_cursor(tmp_path):
    producer = Producer(
        '{"schema_version":2,"candidate":{"title":"准备答辩",'
        '"summary":"用户最近持续准备答辩。",'
        '"source_memory_ids":["l1-1","l1-2","l1-3"]}}'
    )
    reviewer = Reviewer(error=True)
    connection, ledger, service = prepared(tmp_path, producer, reviewer)
    result = run(service)
    assert (producer.calls, reviewer.calls) == (1, 1)
    assert result.run.status == ConsolidationRunStatus.FAILED
    assert result.run.outcome_code == "risk_review_failed"
    assert result.run.model_call_count == 2
    assert ledger.latest_cursor("user:self", ConsolidationStage.L1_TO_L2) is None
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    connection.close()
