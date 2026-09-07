"""V23→V24：新增用户主动出现时段的弱习惯候选与来源。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_routine_candidates (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (
                length(trim(subject_id)) BETWEEN 1 AND 120
            ),
            status TEXT NOT NULL CHECK (status IN ('candidate', 'dismissed')),
            expected_minute INTEGER NOT NULL CHECK (
                expected_minute BETWEEN 0 AND 1439
            ),
            utc_offset_minutes INTEGER NOT NULL CHECK (
                utc_offset_minutes BETWEEN -720 AND 840
            ),
            observation_window_minutes INTEGER NOT NULL CHECK (
                observation_window_minutes = 30
            ),
            evidence_count INTEGER NOT NULL CHECK (evidence_count >= 3),
            distinct_local_dates INTEGER NOT NULL CHECK (
                distinct_local_dates >= 3
            ),
            evidence_fingerprint TEXT NOT NULL CHECK (
                length(evidence_fingerprint) = 64
            ),
            rationale_code TEXT NOT NULL CHECK (
                rationale_code = 'repeated_user_initiated_activity_near_time'
            ),
            generator_version TEXT NOT NULL CHECK (
                length(trim(generator_version)) BETWEEN 1 AND 120
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            UNIQUE (subject_id, evidence_fingerprint)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_routine_one_candidate
            ON companion_routine_candidates (subject_id) WHERE status='candidate';
        CREATE INDEX IF NOT EXISTS idx_companion_routine_subject_recent
            ON companion_routine_candidates (
                subject_id, created_at DESC, id DESC
            );

        CREATE TABLE IF NOT EXISTS companion_routine_candidate_sources (
            candidate_id TEXT NOT NULL,
            user_initiated_event_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            silence_gap_seconds INTEGER,
            evidence_kind TEXT NOT NULL CHECK (
                evidence_kind = 'silence_gap_without_recent_outreach'
            ),
            PRIMARY KEY (candidate_id, user_initiated_event_id),
            FOREIGN KEY (candidate_id)
                REFERENCES companion_routine_candidates (id) ON DELETE CASCADE,
            FOREIGN KEY (user_initiated_event_id)
                REFERENCES companion_user_initiated_interactions (id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_routine_source_event
            ON companion_routine_candidate_sources (user_initiated_event_id);
    """)
