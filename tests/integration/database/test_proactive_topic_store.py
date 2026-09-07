from datetime import UTC, datetime

import pytest

from longmemory.adapters.storage.sqlite_proactive_topic_store import (
    SQLiteProactiveTopicStore,
)
from longmemory.core.proactive import ProactiveTopicSeed, TopicSeedStatus
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema
from longmemory.infrastructure.database.definition import SCHEMA_VERSION


NOW = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)


def insert_scenario(connection, *, status="active", revision=2):
    connection.execute(
        "INSERT INTO scenario_memories "
        "(id,subject_id,title,summary,generated_at,valid_from,valid_to,status,"
        "generator_name,generator_version,revision) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("scenario-1", "user:self", "毕业设计", "用户正在准备毕业设计汇报。",
         NOW.isoformat(), None, None, status, "test", "1", revision),
    )
    connection.commit()


def test_topic_seed_only_accepts_current_active_scenario_and_can_be_disabled(tmp_path):
    connection = open_database(tmp_path / "topic.db")
    initialize_schema(connection)
    insert_scenario(connection)
    store = SQLiteProactiveTopicStore(connection)
    seed = ProactiveTopicSeed(
        "a" * 32, "user:self", "scenario-1", "毕业设计准备得怎么样了？",
        TopicSeedStatus.ACTIVE, NOW, NOW,
    )
    store.create(seed, expected_scenario_revision=2)
    assert store.list("user:self")[0]["scenario_title"] == "毕业设计"
    assert store.disable(seed.id, expected_revision=1, now=NOW) is True
    assert store.list("user:self")[0]["status"] == "disabled"
    connection.close()


def test_topic_seed_rejects_unaccepted_or_changed_scenario(tmp_path):
    connection = open_database(tmp_path / "blocked-topic.db")
    initialize_schema(connection)
    insert_scenario(connection, status="candidate", revision=1)
    store = SQLiteProactiveTopicStore(connection)
    seed = ProactiveTopicSeed(
        "b" * 32, "user:self", "scenario-1", "这条不会被保存。",
        TopicSeedStatus.ACTIVE, NOW, NOW,
    )
    with pytest.raises(ValueError, match="topic_seed_scenario_not_active"):
        store.create(seed, expected_scenario_revision=1)
    connection.execute("UPDATE scenario_memories SET status='active',revision=2")
    with pytest.raises(ValueError, match="topic_seed_scenario_conflict"):
        store.create(seed, expected_scenario_revision=1)
    connection.execute(
        "UPDATE scenario_memories SET valid_from=?,revision=3",
        (datetime(2026, 9, 8, 6, 0, tzinfo=UTC).isoformat(),),
    )
    with pytest.raises(ValueError, match="topic_seed_scenario_not_current"):
        store.create(seed, expected_scenario_revision=3)
    connection.close()


def test_v16_upgrade_adds_empty_topic_table_without_enabling_anything(tmp_path):
    connection = open_database(tmp_path / "v16.db")
    initialize_schema(connection)
    connection.execute("DROP TABLE proactive_topic_seeds")
    connection.execute("PRAGMA user_version=16")
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM proactive_topic_seeds").fetchone()[0] == 0
    connection.close()
