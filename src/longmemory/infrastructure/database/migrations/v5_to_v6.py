"""V5→V6：增加 L2 生命周期事件，并让来源失效触发器留下审计。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE scenario_lifecycle_events (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('manual_end', 'source_retired', 'source_deleted')),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'system')),
    occurred_at TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('candidate', 'active')),
    new_status TEXT NOT NULL CHECK (new_status = 'stale'),
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 2),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE INDEX idx_scenario_lifecycle_scenario
    ON scenario_lifecycle_events (scenario_id, occurred_at);
DROP TRIGGER trg_scenario_stale_on_l1_retire;
DROP TRIGGER trg_scenario_stale_on_l1_delete;
CREATE TRIGGER trg_scenario_stale_on_l1_retire
AFTER UPDATE OF retired_at ON atomic_memories
WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
BEGIN
    INSERT INTO scenario_lifecycle_events
        (id, scenario_id, action, actor_type, occurred_at,
         previous_status, new_status, scenario_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_retired', 'system',
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM scenario_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = NEW.id);
    UPDATE scenario_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = NEW.id);
END;
CREATE TRIGGER trg_scenario_stale_on_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO scenario_lifecycle_events
        (id, scenario_id, action, actor_type, occurred_at,
         previous_status, new_status, scenario_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_deleted', 'system',
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM scenario_memories
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = OLD.id);
    UPDATE scenario_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = OLD.id);
END;
"""


def migrate(connection: Connection) -> None:
    """只增加审计表并替换触发器；不改写已有 L0/L1/L2 行。"""

    connection.executescript(_SQL)
