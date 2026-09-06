"""V10→V11：增加空的低频整理运行账本，不触碰任何既有记忆。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) > 0),
    stage TEXT NOT NULL CHECK (stage IN ('l1_to_l2', 'l2_to_l3')),
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('new_evidence', 'manual', 'rebuild')),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'skipped', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome_code TEXT,
    source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    model_call_count INTEGER NOT NULL DEFAULT 0 CHECK (model_call_count >= 0),
    cursor_recorded_at TEXT,
    cursor_source_id TEXT,
    CHECK (
        (status = 'running' AND finished_at IS NULL AND outcome_code IS NULL)
        OR
        (status <> 'running' AND finished_at IS NOT NULL
            AND length(trim(outcome_code)) > 0)
    ),
    CHECK (
        (status = 'completed' AND source_count > 0
            AND cursor_recorded_at IS NOT NULL
            AND length(trim(cursor_source_id)) > 0)
        OR
        (status <> 'completed' AND cursor_recorded_at IS NULL
            AND cursor_source_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_consolidation_one_running
    ON memory_consolidation_runs (subject_id, stage) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_consolidation_recent
    ON memory_consolidation_runs (subject_id, stage, started_at DESC);
"""


def migrate(connection: Connection) -> None:
    """只创建空账本；升级本身不会生成 L2/L3，也不会调用模型。"""

    connection.executescript(_SQL)
