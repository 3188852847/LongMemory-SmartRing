"""数据库升级工具只操作 pytest 合成库。"""

import sqlite3
from pathlib import Path

from longmemory.infrastructure.database.schema import initialize_schema


def _load_tool():
    import importlib.util
    path = Path(__file__).resolve().parents[3] / "scripts/development/memory_database.py"
    spec = importlib.util.spec_from_file_location("memory_database_tool_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_backup_and_upgrades_copy(tmp_path):
    tool = _load_tool()
    database = tmp_path / "personal-synthetic.db"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    initialize_schema(connection)
    connection.execute("PRAGMA user_version = 3")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript("""
        DROP TRIGGER trg_scenario_stale_on_l1_delete;
        DROP TRIGGER trg_scenario_stale_on_l1_retire;
        DROP TABLE scenario_reviews;
        DROP TABLE scenario_generation_audits;
        DROP TABLE scenario_memory_sources;
        DROP TABLE scenario_memories;
        ALTER TABLE memory_evidence RENAME TO evidence_new;
        CREATE TABLE memory_evidence (
          memory_id TEXT NOT NULL, source_message_id TEXT NOT NULL,
          source_type TEXT NOT NULL CHECK(source_type IN ('user_stated')),
          linked_at TEXT NOT NULL,
          PRIMARY KEY(memory_id, source_message_id, source_type),
          FOREIGN KEY(memory_id) REFERENCES atomic_memories(id) ON DELETE CASCADE,
          FOREIGN KEY(source_message_id) REFERENCES conversation_messages(id) ON DELETE RESTRICT
        );
        DROP TABLE evidence_new;
    """)
    connection.close()

    result = tool.migrate(database, tmp_path / "backups")

    assert result["changed"] is True and len(result["backup_sha256"]) == 64
    assert Path(result["backup"]).is_file()
    with sqlite3.connect(database) as reopened:
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == 5
    with sqlite3.connect(result["backup"]) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 3
