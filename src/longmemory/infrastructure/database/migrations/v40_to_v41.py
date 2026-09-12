"""V40 -> V41：追加 L1 合并的恢复与再应用状态事件。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l1_duplicate_merge_state_events (
            id TEXT PRIMARY KEY,
            merge_event_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('restore', 'reapply')),
            state_revision INTEGER NOT NULL CHECK (state_revision >= 2),
            occurred_at TEXT NOT NULL,
            UNIQUE (merge_event_id, state_revision),
            FOREIGN KEY (merge_event_id)
                REFERENCES l1_duplicate_merge_events (id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l1_duplicate_merge_state_latest
            ON l1_duplicate_merge_state_events (merge_event_id, state_revision DESC);
        """
    )
