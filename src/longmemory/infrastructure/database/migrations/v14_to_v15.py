"""V14→V15：增加默认无记录的主动联系持久设置。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS proactive_policy_settings (
        subject_id TEXT PRIMARY KEY CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
        enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
        utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
        allowed_weekdays_mask INTEGER NOT NULL CHECK (allowed_weekdays_mask BETWEEN 1 AND 127),
        allowed_start_minute INTEGER NOT NULL CHECK (allowed_start_minute BETWEEN 0 AND 1439),
        allowed_end_minute INTEGER NOT NULL CHECK (allowed_end_minute BETWEEN 0 AND 1439),
        daily_limit INTEGER NOT NULL CHECK (daily_limit BETWEEN 1 AND 20),
        minimum_interval_seconds INTEGER NOT NULL CHECK (minimum_interval_seconds BETWEEN 0 AND 604800),
        maximum_lifetime_seconds INTEGER NOT NULL CHECK (maximum_lifetime_seconds BETWEEN 5 AND 1800),
        quiet_until TEXT,
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) BETWEEN 1 AND 120),
        revision INTEGER NOT NULL CHECK (revision >= 1),
        updated_at TEXT NOT NULL,
        CHECK (allowed_start_minute <> allowed_end_minute)
    );
    """)
