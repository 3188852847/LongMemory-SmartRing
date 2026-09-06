"""用独立资源执行一次 L1→L2→L3 低频整理周期。"""

from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import connect, Row

from longmemory.adapters.storage.sqlite_consolidation_run_store import (
    SQLiteConsolidationRunStore,
)
from longmemory.adapters.storage.sqlite_l1_consolidation_source_reader import (
    SQLiteL1ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_l2_consolidation_source_reader import (
    SQLiteL2ConsolidationSourceReader,
)
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.adapters.storage.sqlite_persona_store import SQLitePersonaStore
from longmemory.adapters.storage.sqlite_scenario_store import SQLiteScenarioStore
from longmemory.application.consolidation.l1_to_l2_service import (
    L1ToL2ConsolidationService,
)
from longmemory.application.consolidation.l2_to_l3_service import (
    L2ToL3ConsolidationService,
)
from longmemory.core.memory.consolidation.models import ConsolidationTrigger
from longmemory.infrastructure.database.definition import SCHEMA_VERSION


class LowFrequencyConsolidationCycle:
    """每次调用重开 SQLite；不持有聊天 Runtime 的连接或锁。"""

    def __init__(
        self,
        *,
        database: Path,
        scenario_producer,
        persona_producer,
        risk_reviewer,
        generator_name: str,
        scenario_generator_version: str,
        persona_generator_version: str,
    ) -> None:
        self._database = database.resolve()
        self._scenario_producer = scenario_producer
        self._persona_producer = persona_producer
        self._risk_reviewer = risk_reviewer
        self._generator_name = generator_name
        self._scenario_version = scenario_generator_version
        self._persona_version = persona_generator_version

    def __call__(self, subject_id: str) -> str:
        if not self._database.is_file():
            raise RuntimeError("consolidation_database_missing")
        connection = connect(
            self._database.as_uri() + "?mode=rw", uri=True, timeout=5,
        )
        connection.row_factory = Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("consolidation_database_invalid")
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise RuntimeError("consolidation_database_version_mismatch")

            now = datetime.now(UTC)
            budget_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
            runs = SQLiteConsolidationRunStore(connection)
            l1 = L1ToL2ConsolidationService(
                run_store=runs,
                source_reader=SQLiteL1ConsolidationSourceReader(connection),
                proposal_producer=self._scenario_producer,
                risk_reviewer=self._risk_reviewer,
                memory_store=SQLiteMemoryStore(connection),
                scenario_store=SQLiteScenarioStore(connection),
            ).run_once(
                subject_id=subject_id,
                trigger=ConsolidationTrigger.NEW_EVIDENCE,
                budget_window_start=budget_start,
                generator_name=self._generator_name,
                generator_version=self._scenario_version,
            )
            l2 = L2ToL3ConsolidationService(
                run_store=runs,
                source_reader=SQLiteL2ConsolidationSourceReader(connection),
                consolidation_producer=self._persona_producer,
                risk_reviewer=self._risk_reviewer,
                persona_store=SQLitePersonaStore(connection),
            ).run_once(
                subject_id=subject_id,
                trigger=ConsolidationTrigger.NEW_EVIDENCE,
                budget_window_start=budget_start,
                generator_name=self._generator_name,
                generator_version=self._persona_version,
            )
            return "|".join((self._outcome("l1_to_l2", l1), self._outcome("l2_to_l3", l2)))
        finally:
            connection.close()

    @staticmethod
    def _outcome(stage: str, result) -> str:
        if result.run is not None:
            return f"{stage}:{result.run.status.value}:{result.run.outcome_code}"
        return f"{stage}:{result.trigger_decision.action.value}:{result.trigger_decision.reason.value}"
