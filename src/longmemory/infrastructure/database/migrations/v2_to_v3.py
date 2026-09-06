"""V2→V3：引入主体、双时间字段和可追溯取代关系。"""

from sqlite3 import Connection

_SQL = """
BEGIN IMMEDIATE;
CREATE TABLE atomic_memories_v3 (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    retired_at TEXT,
    superseded_by_id TEXT,
    FOREIGN KEY (superseded_by_id) REFERENCES atomic_memories_v3 (id) ON DELETE SET NULL
);
INSERT INTO atomic_memories_v3 (
    id, subject_id, content, recorded_at, valid_from, valid_to, retired_at, superseded_by_id
)
SELECT id, 'user:self', content, created_at, NULL, NULL, NULL, NULL FROM atomic_memories;
CREATE TABLE memory_evidence_v3 (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated')),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id) REFERENCES atomic_memories_v3 (id) ON DELETE CASCADE,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
INSERT INTO memory_evidence_v3 (memory_id, source_message_id, source_type, linked_at)
SELECT memory_id, source_message_id, source_type, linked_at FROM memory_evidence;
DROP TABLE memory_evidence;
DROP TABLE atomic_memories;
ALTER TABLE atomic_memories_v3 RENAME TO atomic_memories;
ALTER TABLE memory_evidence_v3 RENAME TO memory_evidence;
CREATE INDEX idx_atomic_memories_active_content
    ON atomic_memories (subject_id, content) WHERE retired_at IS NULL;
CREATE INDEX idx_memory_evidence_source_message ON memory_evidence (source_message_id);
COMMIT;
"""


def migrate(connection: Connection) -> None:
    """在表重建后恢复外键检查，并拒绝带损坏关系的结果。"""

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
