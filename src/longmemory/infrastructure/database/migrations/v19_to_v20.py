"""V19→V20：新增不含消息正文的陪伴互动结果事件。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_interaction_events (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (
                length(trim(subject_id)) BETWEEN 1 AND 120
            ),
            event_kind TEXT NOT NULL CHECK (
                event_kind = 'subsequent_user_message_observed'
            ),
            outreach_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            latency_seconds INTEGER NOT NULL CHECK (latency_seconds >= 0),
            evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'temporal_order'),
            recorder_version TEXT NOT NULL CHECK (
                length(trim(recorder_version)) BETWEEN 1 AND 120
            ),
            UNIQUE (outreach_id, event_kind),
            FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id)
                ON DELETE RESTRICT,
            FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_interaction_subject_recent
            ON companion_interaction_events (subject_id, occurred_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_companion_interaction_source_message
            ON companion_interaction_events (source_message_id);
    """)
