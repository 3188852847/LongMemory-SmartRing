"""V8→V9：增加显式 L3 取代关系；不改变既有画像状态。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE IF NOT EXISTS persona_replacements (
    candidate_persona_id TEXT NOT NULL,
    replaced_persona_id TEXT NOT NULL,
    target_revision INTEGER NOT NULL CHECK (target_revision >= 1),
    linked_at TEXT NOT NULL,
    applied_at TEXT,
    PRIMARY KEY (candidate_persona_id, replaced_persona_id),
    CHECK (candidate_persona_id <> replaced_persona_id),
    FOREIGN KEY (candidate_persona_id) REFERENCES persona_memories (id) ON DELETE RESTRICT,
    FOREIGN KEY (replaced_persona_id) REFERENCES persona_memories (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_persona_replacements_target
    ON persona_replacements (replaced_persona_id, applied_at);
"""


def migrate(connection: Connection) -> None:
    """只创建空关系表；既有 L0–L3 内容、状态和修订号保持原样。"""

    connection.executescript(_SQL)
