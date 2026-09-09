"""V28 只记录 L1 删除身份与时间，不暗中保留被删正文。"""

from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def insert_memory(connection, memory_id="memory-1"):
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id,subject_id,content,recorded_at) VALUES (?,?,?,?)",
        (memory_id, "user:self", "这段合成正文不应进入删除审计。",
         "2026-09-09T08:00:00+00:00"),
    )
    connection.commit()


def test_delete_trigger_records_identity_but_not_content(tmp_path):
    connection = open_database(tmp_path / "audit.db")
    initialize_schema(connection)
    insert_memory(connection)

    connection.execute("DELETE FROM atomic_memories WHERE id='memory-1'")
    connection.commit()
    event = connection.execute("SELECT * FROM l1_deletion_events").fetchone()
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(l1_deletion_events)")
    }

    assert event["memory_id"] == "memory-1"
    assert event["subject_id"] == "user:self"
    assert event["deleted_at"].endswith("+00:00")
    assert "content" not in columns
    assert "合成正文" not in str(dict(event))
    connection.close()


def test_v27_upgrade_adds_empty_audit_and_does_not_backfill(tmp_path):
    connection = open_database(tmp_path / "v27.db")
    initialize_schema(connection)
    insert_memory(connection)
    connection.executescript("""
        DROP TRIGGER trg_audit_l1_delete;
        DROP INDEX idx_l1_deletion_events_subject_time;
        DROP TABLE l1_deletion_events;
        PRAGMA user_version=27;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM l1_deletion_events").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
