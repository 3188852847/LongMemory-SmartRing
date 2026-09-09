"""V27 -> V28：记录不含正文的 L1 删除审计事件。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS l1_deletion_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_deletion_events_subject_time
    ON l1_deletion_events (subject_id, deleted_at DESC, id DESC);
CREATE TRIGGER IF NOT EXISTS trg_audit_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO l1_deletion_events (id, memory_id, subject_id, deleted_at)
    VALUES (
        lower(hex(randomblob(16))), OLD.id, OLD.subject_id,
        strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
    );
END;
"""


def migrate(connection) -> None:
    """只新增空审计表和触发器，不回填无法证明的历史删除。"""

    connection.executescript(MIGRATION_SQL)
