"""V3→V4：允许证据显式标记为用户人工纠正。"""

from sqlite3 import Connection

_SQL = """
BEGIN IMMEDIATE;
CREATE TABLE memory_evidence_v4 (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
INSERT INTO memory_evidence_v4 (memory_id, source_message_id, source_type, linked_at)
SELECT memory_id, source_message_id, source_type, linked_at FROM memory_evidence;
DROP TABLE memory_evidence;
ALTER TABLE memory_evidence_v4 RENAME TO memory_evidence;
CREATE INDEX idx_memory_evidence_source_message ON memory_evidence (source_message_id);
COMMIT;
"""


def migrate(connection: Connection) -> None:
    """用重建表更新 SQLite CHECK 约束，并复核全部外键。"""

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(_SQL)
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"数据库升级后发现外键关系损坏：{violations}")
