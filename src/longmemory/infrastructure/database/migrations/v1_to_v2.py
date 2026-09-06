"""V1→V2：把原子记忆的单一来源回填为独立证据关系。"""

from sqlite3 import Connection

_CREATE_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated')),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);
"""
_BACKFILL_SQL = """
INSERT OR IGNORE INTO memory_evidence (memory_id, source_message_id, source_type, linked_at)
SELECT id, source_message_id, 'user_stated', created_at FROM atomic_memories;
"""


def migrate(connection: Connection) -> None:
    """保留 V1 旧列，先建立后续重建表需要的证据关系。"""

    connection.executescript(_CREATE_EVIDENCE_SQL)
    connection.executescript(_BACKFILL_SQL)
