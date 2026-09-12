"""V42 -> V43：追加所有者对 L2 影子门控的人工复核事件。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l2_sufficiency_shadow_review_events (
            id TEXT PRIMARY KEY,
            user_message_id TEXT NOT NULL,
            review_revision INTEGER NOT NULL CHECK (review_revision >= 1),
            verdict TEXT NOT NULL CHECK (verdict IN ('correct','incorrect','uncertain')),
            reason_code TEXT NOT NULL CHECK (reason_code IN (
                'agreement','missed_support','false_support','ambiguous_query',
                'stale_content','other'
            )),
            occurred_at TEXT NOT NULL,
            UNIQUE (user_message_id, review_revision),
            FOREIGN KEY (user_message_id)
                REFERENCES l2_sufficiency_shadow_runs (user_message_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l2_shadow_review_latest
            ON l2_sufficiency_shadow_review_events
                (user_message_id, review_revision DESC);
        """
    )
