"""V30 圆屏回答回执只新增可追溯问答关联，不猜测旧会话。"""

from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.schema import initialize_schema


def test_v29_upgrade_adds_empty_round_screen_turn_table(tmp_path):
    connection = open_database(tmp_path / "v29.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP INDEX idx_round_screen_turns_completed;
        DROP TABLE round_screen_turns;
        PRAGMA user_version=29;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM round_screen_turns").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
