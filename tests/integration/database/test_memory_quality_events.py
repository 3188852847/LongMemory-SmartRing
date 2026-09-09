"""V29 只为所有者确认的漏记保存可回溯身份，不复制正文。"""

from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def test_v28_upgrade_adds_empty_quality_events_without_backfill(tmp_path):
    connection = open_database(tmp_path / "v28.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_memory_quality_events_time;
        DROP INDEX idx_memory_quality_event_source_kind;
        DROP TABLE memory_quality_events;
        PRAGMA user_version=28;
    """)

    initialize_schema(connection)

    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(memory_quality_events)")
    }
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM memory_quality_events").fetchone()[0] == 0
    assert "content" not in columns
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
