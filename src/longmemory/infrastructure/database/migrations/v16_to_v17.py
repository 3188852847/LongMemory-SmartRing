"""V16→V17：新增由所有者明确批准的主动话题素材。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS proactive_topic_seeds (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL CHECK (length(trim(subject_id)) BETWEEN 1 AND 120),
            scenario_id TEXT NOT NULL,
            prompt_text TEXT NOT NULL CHECK (length(trim(prompt_text)) BETWEEN 1 AND 120),
            status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_proactive_topic_seeds_subject
            ON proactive_topic_seeds (subject_id, status, created_at DESC);
    """)
