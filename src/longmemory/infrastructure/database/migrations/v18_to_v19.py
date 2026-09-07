"""V18→V19：新增一次性开发定时验证授权。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS proactive_schedule_overrides (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
            local_date TEXT NOT NULL CHECK (length(local_date) = 10),
            scheduled_minute INTEGER NOT NULL CHECK (scheduled_minute BETWEEN 0 AND 1439),
            policy_revision INTEGER NOT NULL CHECK (policy_revision >= 1),
            status TEXT NOT NULL CHECK (status IN ('armed', 'consumed', 'cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            consumption_reason TEXT CHECK (
                consumption_reason IS NULL
                OR length(trim(consumption_reason)) BETWEEN 1 AND 120
            ),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            CHECK (
                (status = 'armed' AND consumption_reason IS NULL)
                OR (status <> 'armed' AND consumption_reason IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_proactive_schedule_override_one_armed
            ON proactive_schedule_overrides (subject_id) WHERE status='armed';
        CREATE INDEX IF NOT EXISTS idx_proactive_schedule_override_recent
            ON proactive_schedule_overrides (subject_id, created_at DESC, id DESC);
    """)
