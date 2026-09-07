from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_companion_absence_strategy_store import (
    SQLiteCompanionAbsenceStrategyVersionStore,
)
from longmemory.application.companion_absence_strategy import (
    CompanionAbsenceStrategyVersionService,
)
from longmemory.core.companion import CompanionStrategyReplayEvidence
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)


def add_candidate(connection):
    connection.execute(
        "INSERT INTO companion_routine_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("candidate-1", "user:self", "candidate", 780, 480, 30, 3, 3,
         "a" * 64, "repeated_user_initiated_activity_near_time",
         "test-generator", NOW.isoformat(), NOW.isoformat(), 1),
    )
    connection.commit()


def test_strategy_version_persists_replay_binding_without_activation(tmp_path):
    connection = open_database(tmp_path / "strategy.db")
    initialize_schema(connection)
    add_candidate(connection)
    store = SQLiteCompanionAbsenceStrategyVersionStore(connection)

    result = CompanionAbsenceStrategyVersionService(
        store, clock=lambda: NOW, id_factory=lambda: "version-1",
    ).create_from_candidate(
        "candidate-1", subject_id="user:self", expected_candidate_revision=1,
        allowed_weekdays=(0, 2, 4),
        replay=CompanionStrategyReplayEvidence(
            protocol="companion-absence-offline-replay-v1",
            dataset_name="companion_absence_replay", dataset_version="1.0.0",
            dataset_sha256="b" * 64, case_count=16, matched_count=16,
            unsafe_allow_count=0, gate_passed=True, replayed_at=NOW,
        ),
    )
    connection.close()

    reopened = open_database(tmp_path / "strategy.db")
    saved = SQLiteCompanionAbsenceStrategyVersionStore(reopened).list("user:self")
    assert result.outcome == "version_created"
    assert len(saved) == 1
    assert saved[0].allowed_weekdays == (0, 2, 4)
    assert saved[0].replay_case_count == saved[0].replay_matched_count == 16
    assert saved[0].replay_gate_passed is True
    assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []
    # V25 只保存不可变版本；没有当前激活指针，更不会修改 P4 设置。
    assert reopened.execute(
        "SELECT automatic_enabled FROM proactive_policy_settings WHERE subject_id='user:self'"
    ).fetchone() is None
    reopened.close()


def test_v24_upgrade_adds_empty_strategy_version_table(tmp_path):
    connection = open_database(tmp_path / "v24.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_companion_absence_versions_subject;
        DROP TABLE companion_absence_strategy_versions;
        PRAGMA user_version=24;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM companion_absence_strategy_versions"
    ).fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
