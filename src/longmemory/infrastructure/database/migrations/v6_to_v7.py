"""V6→V7：增加空的 L3 用户画像候选结构，不生成或改写个人记忆。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE IF NOT EXISTS persona_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('preference', 'habit', 'interaction_style', 'behavior_pattern')
    ),
    basis TEXT NOT NULL CHECK (basis IN ('user_declared', 'system_inferred')),
    label TEXT NOT NULL CHECK (length(trim(label)) BETWEEN 1 AND 120),
    statement TEXT NOT NULL CHECK (length(trim(statement)) BETWEEN 1 AND 1000),
    generated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'rejected', 'stale')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);
CREATE TABLE IF NOT EXISTS persona_sources (
    persona_id TEXT NOT NULL,
    source_layer TEXT NOT NULL CHECK (source_layer IN ('l1', 'l2')),
    source_id TEXT NOT NULL,
    source_content_snapshot TEXT NOT NULL CHECK (length(trim(source_content_snapshot)) > 0),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (persona_id, source_layer, source_id),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_persona_sources_source ON persona_sources (source_layer, source_id);
CREATE TABLE IF NOT EXISTS persona_generation_audits (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE,
    basis TEXT NOT NULL CHECK (basis IN ('user_declared', 'system_inferred')),
    generator_name TEXT NOT NULL CHECK (length(trim(generator_name)) > 0),
    generator_version TEXT NOT NULL CHECK (length(trim(generator_version)) > 0),
    generated_at TEXT NOT NULL,
    source_count INTEGER NOT NULL CHECK (source_count >= 1),
    source_message_count INTEGER NOT NULL CHECK (source_message_count >= 1),
    observation_day_count INTEGER NOT NULL CHECK (observation_day_count >= 1),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS persona_reviews (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type = 'user'),
    reviewed_at TEXT NOT NULL,
    persona_revision INTEGER NOT NULL CHECK (persona_revision >= 1),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
"""


def migrate(connection: Connection) -> None:
    """只创建 L3 空表；不得扫描 L0/L1/L2 或伪造画像候选。"""

    connection.executescript(_SQL)
