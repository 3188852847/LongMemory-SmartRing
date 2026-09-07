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


def test_v15_upgrade_preserves_contact_permission_but_keeps_automatic_off(tmp_path):
    connection = open_database(tmp_path / "v15.db")
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO proactive_policy_settings "
        "(subject_id,enabled,utc_offset_minutes,allowed_weekdays_mask,"
        "allowed_start_minute,allowed_end_minute,daily_limit,"
        "minimum_interval_seconds,maximum_lifetime_seconds,quiet_until,"
        "policy_version,revision,updated_at) "
        "VALUES ('user:self',1,480,127,600,1260,1,21600,300,NULL,"
        "'proactive-contact-policy-v1',4,?)",
        (NOW.isoformat(),),
    )
    connection.executescript("""
        ALTER TABLE proactive_policy_settings DROP COLUMN automatic_enabled;
        ALTER TABLE proactive_policy_settings DROP COLUMN scheduled_minute;
        ALTER TABLE proactive_policy_settings DROP COLUMN greeting_text;
        PRAGMA user_version=15;
    """)

    initialize_schema(connection)

    restored = SQLiteProactivePolicyStore(connection).get("user:self")
    assert restored.config.enabled is True
    assert restored.config.policy_version == "proactive-contact-policy-v2"
    assert restored.revision == 4
    assert restored.automatic_enabled is False
    assert restored.scheduled_minute == 600
    assert restored.greeting_text == "下午好，今天过得怎么样？"
    assert restored.topic_enabled is False
    connection.close()


def test_v17_upgrade_keeps_memory_topics_off_and_adds_outreach_provenance(tmp_path):
    from longmemory.infrastructure.database.migrations.v17_to_v18 import migrate

    connection = open_database(tmp_path / "v17.db")
    connection.executescript("""
        CREATE TABLE proactive_policy_settings (subject_id TEXT PRIMARY KEY);
        CREATE TABLE proactive_topic_seeds (id TEXT PRIMARY KEY);
        CREATE TABLE proactive_outreach (id TEXT PRIMARY KEY);
    """)
    migrate(connection)

    policy_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(proactive_policy_settings)")
    }
    assert "topic_enabled" in policy_columns
    columns = {row[1] for row in connection.execute("PRAGMA table_info(proactive_outreach)")}
    assert {"topic_seed_id", "topic_seed_revision"} <= columns
    connection.close()
