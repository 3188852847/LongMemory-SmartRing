"""当前 SQLite V4 的完整结构定义；不包含历史迁移步骤。"""

SCHEMA_VERSION = 4

LATEST_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS atomic_memories (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    retired_at TEXT,
    superseded_by_id TEXT,
    FOREIGN KEY (superseded_by_id) REFERENCES atomic_memories (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_atomic_memories_active_content
    ON atomic_memories (subject_id, content) WHERE retired_at IS NULL;
CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
    FOREIGN KEY (source_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);
"""
