"""V20→V21：新增用户明确拒绝主动话题的审计事件。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_feedback_events (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (
                length(trim(subject_id)) BETWEEN 1 AND 120
            ),
            outreach_id TEXT NOT NULL,
            topic_seed_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            feedback_kind TEXT NOT NULL CHECK (feedback_kind = 'reject_topic'),
            action_kind TEXT NOT NULL CHECK (action_kind = 'topic_seed_disabled'),
            evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'user_explicit'),
            interpreter_version TEXT NOT NULL CHECK (
                length(trim(interpreter_version)) BETWEEN 1 AND 120
            ),
            FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id)
                ON DELETE RESTRICT,
            FOREIGN KEY (topic_seed_id) REFERENCES proactive_topic_seeds (id)
                ON DELETE RESTRICT,
            FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_feedback_subject_recent
            ON companion_feedback_events (subject_id, occurred_at DESC, id DESC);
    """)
