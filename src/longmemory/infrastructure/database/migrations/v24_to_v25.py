"""V24→V25：新增不可变缺席陪伴策略版本与离线回放绑定。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS companion_absence_strategy_versions (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
            source_candidate_id TEXT NOT NULL,
            source_candidate_revision INTEGER NOT NULL CHECK (source_candidate_revision >= 1),
            expected_minute INTEGER NOT NULL CHECK (expected_minute BETWEEN 0 AND 1439),
            grace_minutes INTEGER NOT NULL CHECK (grace_minutes BETWEEN 15 AND 360),
            utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
            allowed_weekdays_mask INTEGER NOT NULL CHECK (allowed_weekdays_mask BETWEEN 1 AND 127),
            trigger_policy_version TEXT NOT NULL CHECK (length(trim(trigger_policy_version)) BETWEEN 1 AND 120),
            replay_protocol TEXT NOT NULL CHECK (length(trim(replay_protocol)) BETWEEN 1 AND 120),
            replay_dataset_name TEXT NOT NULL CHECK (length(trim(replay_dataset_name)) BETWEEN 1 AND 120),
            replay_dataset_version TEXT NOT NULL CHECK (length(trim(replay_dataset_version)) BETWEEN 1 AND 120),
            replay_dataset_sha256 TEXT NOT NULL CHECK (length(replay_dataset_sha256) = 64),
            parameter_fingerprint TEXT NOT NULL CHECK (length(parameter_fingerprint) = 64),
            replay_case_count INTEGER NOT NULL CHECK (replay_case_count > 0),
            replay_matched_count INTEGER NOT NULL CHECK (replay_matched_count BETWEEN 0 AND replay_case_count),
            replay_unsafe_allow_count INTEGER NOT NULL CHECK (replay_unsafe_allow_count >= 0),
            replay_gate_passed INTEGER NOT NULL CHECK (replay_gate_passed IN (0,1)),
            replayed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (expected_minute + grace_minutes < 1440),
            CHECK (replay_gate_passed = (replay_matched_count = replay_case_count AND replay_unsafe_allow_count = 0)),
            UNIQUE (subject_id, parameter_fingerprint),
            FOREIGN KEY (source_candidate_id) REFERENCES companion_routine_candidates (id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_absence_versions_subject
            ON companion_absence_strategy_versions (subject_id, created_at DESC, id DESC);
    """)
