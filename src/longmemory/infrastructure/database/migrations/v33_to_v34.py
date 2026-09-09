"""V33 -> V34：增加由当前 L1 派生、默认不投递的跟进候选。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS companion_follow_up_candidates (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
    source_memory_id TEXT NOT NULL,
    source_content_sha256 TEXT NOT NULL CHECK (
        length(source_content_sha256) = 64
        AND source_content_sha256 = lower(source_content_sha256)
        AND source_content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    prompt_text TEXT NOT NULL CHECK (length(trim(prompt_text)) BETWEEN 1 AND 160),
    follow_up_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    FOREIGN KEY (source_memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_companion_follow_up_subject_due
    ON companion_follow_up_candidates (subject_id, status, follow_up_at, id);
"""


def migrate(connection) -> None:
    connection.executescript(MIGRATION_SQL)
