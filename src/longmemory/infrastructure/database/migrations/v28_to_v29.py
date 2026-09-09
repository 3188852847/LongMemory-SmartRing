"""V28 -> V29：记录不含正文的记忆质量人工信号。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS memory_quality_events (
    id TEXT PRIMARY KEY,
    event_kind TEXT NOT NULL CHECK (event_kind = 'owner_confirmed_missed_extraction'),
    source_message_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    resolution TEXT NOT NULL CHECK (resolution IN ('created', 'evidence_added')),
    occurred_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_quality_event_source_kind
    ON memory_quality_events (source_message_id, event_kind);
CREATE INDEX IF NOT EXISTS idx_memory_quality_events_time
    ON memory_quality_events (occurred_at DESC, id DESC);
"""


def migrate(connection) -> None:
    """只新增空事件表；不从既有证据时间猜测历史漏记。"""

    connection.executescript(MIGRATION_SQL)
