"""V22→V23：记录长静默后、非主动问候引出的用户主动出现时间。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_user_initiated_interactions (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (
                length(trim(subject_id)) BETWEEN 1 AND 120
            ),
            source_message_id TEXT NOT NULL UNIQUE,
            occurred_at TEXT NOT NULL,
            previous_user_message_at TEXT,
            silence_gap_seconds INTEGER CHECK (
                silence_gap_seconds IS NULL OR silence_gap_seconds >= 14400
            ),
            evidence_kind TEXT NOT NULL CHECK (
                evidence_kind = 'silence_gap_without_recent_outreach'
            ),
            detector_version TEXT NOT NULL CHECK (
                length(trim(detector_version)) BETWEEN 1 AND 120
            ),
            CHECK (
                (previous_user_message_at IS NULL AND silence_gap_seconds IS NULL)
                OR (previous_user_message_at IS NOT NULL
                    AND silence_gap_seconds IS NOT NULL)
            ),
            FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_user_initiated_subject_recent
            ON companion_user_initiated_interactions (
                subject_id, occurred_at DESC, id DESC
            );
    """)
