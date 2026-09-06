"""V4→V5：增加可复核、可失效且保留 L1 快照的 L2 场景结构。"""

from sqlite3 import Connection

_SQL = """
CREATE TABLE scenario_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 120),
    summary TEXT NOT NULL CHECK (length(trim(summary)) BETWEEN 1 AND 2000),
    generated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'rejected', 'stale')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);
CREATE TABLE scenario_memory_sources (
    scenario_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    memory_content_snapshot TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (scenario_id, memory_id),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE INDEX idx_scenario_sources_memory ON scenario_memory_sources (memory_id);
CREATE TABLE scenario_generation_audits (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    generator_name TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_memory_count INTEGER NOT NULL CHECK (source_memory_count >= 2),
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 2),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE TABLE scenario_reviews (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user')),
    reviewed_at TEXT NOT NULL,
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 1),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
CREATE TRIGGER trg_scenario_stale_on_l1_retire
AFTER UPDATE OF retired_at ON atomic_memories
WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
BEGIN
    UPDATE scenario_memories SET status = 'stale', revision = revision + 1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = NEW.id);
END;
CREATE TRIGGER trg_scenario_stale_on_l1_delete
BEFORE DELETE ON atomic_memories
BEGIN
    UPDATE scenario_memories SET status = 'stale', revision = revision + 1
    WHERE status IN ('candidate', 'active')
      AND id IN (SELECT scenario_id FROM scenario_memory_sources WHERE memory_id = OLD.id);
END;
"""


def migrate(connection: Connection) -> None:
    """只增加空 L2 表，不改写任何现有 L0/L1 内容。"""

    connection.executescript(_SQL)
