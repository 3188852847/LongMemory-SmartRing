"""V39 -> V40：逐条记录 L1 合并新增的来源关联。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l1_duplicate_merge_evidence (
            merge_event_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
            linked_at TEXT NOT NULL,
            PRIMARY KEY (merge_event_id, source_message_id, source_type),
            FOREIGN KEY (merge_event_id)
                REFERENCES l1_duplicate_merge_events (id) ON DELETE CASCADE,
            FOREIGN KEY (source_message_id)
                REFERENCES conversation_messages (id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_l1_duplicate_merge_evidence_source
            ON l1_duplicate_merge_evidence (source_message_id, merge_event_id);
        """
    )
