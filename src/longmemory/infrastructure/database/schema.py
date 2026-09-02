"""V0.1 SQLite 初始结构及版本信息。"""

from sqlite3 import Connection


SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS atomic_memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (source_message_id)
        REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_atomic_memories_source_message
    ON atomic_memories (source_message_id);
"""


def initialize_schema(connection: Connection) -> None:
    """创建当前版本所需的表、约束和索引。"""

    connection.executescript(_SCHEMA_SQL)

    # user_version 是 SQLite 内置的整数版本槽。
    # 后续数据库结构变化时，可以据此执行迁移。
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()