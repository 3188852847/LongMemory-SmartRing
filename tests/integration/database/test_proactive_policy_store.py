from datetime import UTC, datetime, timedelta

import pytest

from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 6, 23, 30, tzinfo=UTC)


def test_missing_row_is_default_off_and_saved_settings_survive_reopen(tmp_path):
    path = tmp_path / "policy.db"
    connection = open_database(path)
    initialize_schema(connection)
    store = SQLiteProactivePolicyStore(connection)
    assert store.get("user:self").revision == 0
    assert store.get("user:self").config.enabled is False
    saved = ProactivePolicySettings(
        "user:self",
        OutreachPolicyConfig(
            enabled=True, allowed_weekdays=(0, 2, 4), daily_limit=2,
            minimum_interval=timedelta(hours=8),
        ),
        NOW + timedelta(hours=1), 1, NOW,
    )
    store.save(saved, expected_revision=0)
    connection.close()

    connection = open_database(path)
    restored = SQLiteProactivePolicyStore(connection).get("user:self")
    assert restored == saved
    connection.close()


def test_revision_prevents_stale_overwrite(tmp_path):
    connection = open_database(tmp_path / "conflict.db")
    initialize_schema(connection)
    store = SQLiteProactivePolicyStore(connection)
    settings = ProactivePolicySettings(
        "user:self", OutreachPolicyConfig(), None, 1, NOW,
    )
    store.save(settings, expected_revision=0)
    with pytest.raises(ValueError, match="proactive_settings_conflict"):
        store.save(settings, expected_revision=0)
    assert store.get("user:self") == settings
    connection.close()
