"""V13→V14：增加空的主动交流当前投影与只追加事件账本。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE IF NOT EXISTS proactive_outreach (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
        'manual_test', 'explicit_schedule', 'inactivity_rule', 'habit_candidate'
    )),
    trigger_reason_code TEXT NOT NULL CHECK (
        length(trim(trigger_reason_code)) BETWEEN 1 AND 120
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 500),
    created_at TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    state_changed_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (
        length(trim(idempotency_key)) BETWEEN 1 AND 160
    ),
    policy_version TEXT CHECK (
        policy_version IS NULL OR length(trim(policy_version)) BETWEEN 1 AND 120
    ),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    failure_reason TEXT CHECK (
        failure_reason IS NULL OR length(trim(failure_reason)) BETWEEN 1 AND 120
    ),
    CHECK (
        (state = 'failed' AND failure_reason IS NOT NULL)
        OR (state <> 'failed' AND failure_reason IS NULL)
    ),
    UNIQUE (subject_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_proactive_outreach_recent
    ON proactive_outreach (subject_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_proactive_outreach_due
    ON proactive_outreach (state, scheduled_for, expires_at);

CREATE TABLE IF NOT EXISTS proactive_outreach_events (
    id TEXT PRIMARY KEY,
    outreach_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    previous_state TEXT CHECK (previous_state IS NULL OR previous_state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    new_state TEXT NOT NULL CHECK (new_state IN (
        'candidate', 'blocked', 'queued', 'transport_sent',
        'device_acknowledged', 'played', 'expired', 'cancelled', 'failed'
    )),
    reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) BETWEEN 1 AND 120),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN (
        'system_created', 'policy_decision', 'server_queue', 'transport_write',
        'device_ack', 'user_observed', 'system_recovery'
    )),
    occurred_at TEXT NOT NULL,
    UNIQUE (outreach_id, sequence),
    FOREIGN KEY (outreach_id) REFERENCES proactive_outreach (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_proactive_events_outreach
    ON proactive_outreach_events (outreach_id, sequence);
"""


def migrate(connection: Connection) -> None:
    """只增加空表；不创建候选、不调度、不投递。"""

    connection.executescript(_SQL)
