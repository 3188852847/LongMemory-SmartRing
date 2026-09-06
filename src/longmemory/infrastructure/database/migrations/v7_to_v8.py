"""V7→V8：增加 L3 来源失效审计与传播，不生成画像。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE IF NOT EXISTS persona_lifecycle_events (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('source_retired', 'source_deleted', 'source_stale')),
    source_layer TEXT NOT NULL CHECK (source_layer IN ('l1', 'l2')),
    source_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('candidate', 'active')),
    new_status TEXT NOT NULL CHECK (new_status = 'stale'),
    persona_revision INTEGER NOT NULL CHECK (persona_revision >= 2),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_persona_lifecycle_persona
    ON persona_lifecycle_events (persona_id, occurred_at);
CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l1_retire
AFTER UPDATE OF retired_at ON atomic_memories
WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_retired', 'l1', NEW.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l1' AND source_id=NEW.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l1' AND source_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_deleted', 'l1', OLD.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l1' AND source_id=OLD.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l1' AND source_id=OLD.id);
END;
CREATE TRIGGER IF NOT EXISTS trg_persona_stale_on_l2_stale
AFTER UPDATE OF status ON scenario_memories
WHEN OLD.status IN ('candidate', 'active') AND NEW.status='stale'
BEGIN
    INSERT INTO persona_lifecycle_events
        (id, persona_id, action, source_layer, source_id, occurred_at,
         previous_status, new_status, persona_revision)
    SELECT lower(hex(randomblob(16))), id, 'source_stale', 'l2', NEW.id,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), status, 'stale', revision + 1
    FROM persona_memories WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l2' AND source_id=NEW.id);
    UPDATE persona_memories SET status='stale', revision=revision+1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT persona_id FROM persona_sources WHERE source_layer='l2' AND source_id=NEW.id);
END;
"""


def migrate(connection: Connection) -> None:
    """只增加审计表和触发器；既有 V7 数据不改写。"""

    connection.executescript(_SQL)
