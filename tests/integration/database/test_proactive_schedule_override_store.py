from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_proactive_schedule_override_store import (
    SQLiteProactiveScheduleOverrideStore,
)
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 4, 59, tzinfo=UTC)


def test_one_armed_override_per_subject_and_explicit_cancel(tmp_path):
    connection = open_database(tmp_path / "override.db")
    initialize_schema(connection)
    store = SQLiteProactiveScheduleOverrideStore(connection)
    armed = store.arm(
        override_id="a" * 32, subject_id="user:self",
        local_date="2026-09-07", scheduled_minute=780, policy_revision=1, now=NOW,
    )
    assert armed["status"] == "armed" and armed["revision"] == 1
    with pytest.raises(ValueError, match="already_armed"):
        store.arm(
            override_id="b" * 32, subject_id="user:self",
            local_date="2026-09-07", scheduled_minute=780, policy_revision=1, now=NOW,
        )
    cancelled = store.finish(
        armed["id"], subject_id="user:self", expected_revision=1,
        status="cancelled", reason="owner_cancelled", now=NOW,
    )
    assert cancelled["status"] == "cancelled"
    assert cancelled["consumption_reason"] == "owner_cancelled"
    assert store.get_armed("user:self") is None
    assert store.get_latest("user:self")["status"] == "cancelled"
    connection.close()


def test_v18_upgrade_adds_empty_override_table(tmp_path):
    connection = open_database(tmp_path / "v18.db")
    initialize_schema(connection)
    connection.execute("DROP TABLE proactive_schedule_overrides")
    connection.execute("PRAGMA user_version=18")
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute(
        "SELECT count(*) FROM proactive_schedule_overrides"
    ).fetchone()[0] == 0
    connection.close()
