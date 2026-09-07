"""V25 -> V26：增加缺席策略单一当前指针和只追加切换审计。"""

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS companion_absence_strategy_selections (
    subject_id TEXT PRIMARY KEY,
    current_version_id TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_version_id) REFERENCES companion_absence_strategy_versions (id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS companion_absence_strategy_switch_events (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    previous_version_id TEXT,
    selected_version_id TEXT,
    action TEXT NOT NULL CHECK (action IN ('activate','deactivate','rollback')),
    pointer_revision INTEGER NOT NULL CHECK (pointer_revision >= 1),
    created_at TEXT NOT NULL,
    CHECK ((action = 'deactivate' AND selected_version_id IS NULL)
        OR (action IN ('activate','rollback') AND selected_version_id IS NOT NULL)),
    UNIQUE (subject_id, pointer_revision),
    FOREIGN KEY (previous_version_id) REFERENCES companion_absence_strategy_versions (id) ON DELETE RESTRICT,
    FOREIGN KEY (selected_version_id) REFERENCES companion_absence_strategy_versions (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_companion_absence_switch_subject
    ON companion_absence_strategy_switch_events (subject_id, pointer_revision DESC);
"""


def migrate(connection) -> None:
    connection.executescript(MIGRATION_SQL)
