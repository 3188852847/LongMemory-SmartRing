"""V0.1 SQLite 当前结构及非破坏性升级路径。"""

from sqlite3 import Connection


SCHEMA_VERSION = 4

_LATEST_SCHEMA_SQL = """
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

    FOREIGN KEY (superseded_by_id)
        REFERENCES atomic_memories (id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_atomic_memories_active_content
    ON atomic_memories (subject_id, content)
    WHERE retired_at IS NULL;

CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
    linked_at TEXT NOT NULL,

    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id)
        REFERENCES atomic_memories (id)
        ON DELETE CASCADE,
    FOREIGN KEY (source_message_id)
        REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);
"""

_CREATE_V2_EVIDENCE_SQL = """
CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated')),
    linked_at TEXT NOT NULL,

    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id)
        REFERENCES atomic_memories (id)
        ON DELETE CASCADE,
    FOREIGN KEY (source_message_id)
        REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);
"""

_BACKFILL_V1_EVIDENCE_SQL = """
INSERT OR IGNORE INTO memory_evidence (
    memory_id,
    source_message_id,
    source_type,
    linked_at
)
SELECT
    id,
    source_message_id,
    'user_stated',
    created_at
FROM atomic_memories;
"""

_MIGRATE_V2_TO_V3_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE atomic_memories_v3 (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    content TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    retired_at TEXT,
    superseded_by_id TEXT,

    FOREIGN KEY (superseded_by_id)
        REFERENCES atomic_memories_v3 (id)
        ON DELETE SET NULL
);

INSERT INTO atomic_memories_v3 (
    id,
    subject_id,
    content,
    recorded_at,
    valid_from,
    valid_to,
    retired_at,
    superseded_by_id
)
SELECT
    id,
    'user:self',
    content,
    created_at,
    NULL,
    NULL,
    NULL,
    NULL
FROM atomic_memories;

CREATE TABLE memory_evidence_v3 (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated')),
    linked_at TEXT NOT NULL,

    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id)
        REFERENCES atomic_memories_v3 (id)
        ON DELETE CASCADE,
    FOREIGN KEY (source_message_id)
        REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);

INSERT INTO memory_evidence_v3 (
    memory_id,
    source_message_id,
    source_type,
    linked_at
)
SELECT
    memory_id,
    source_message_id,
    source_type,
    linked_at
FROM memory_evidence;

DROP TABLE memory_evidence;
DROP TABLE atomic_memories;

ALTER TABLE atomic_memories_v3 RENAME TO atomic_memories;
ALTER TABLE memory_evidence_v3 RENAME TO memory_evidence;

CREATE INDEX idx_atomic_memories_active_content
    ON atomic_memories (subject_id, content)
    WHERE retired_at IS NULL;

CREATE INDEX idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);

COMMIT;
"""

_MIGRATE_V3_TO_V4_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE memory_evidence_v4 (
    memory_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('user_stated', 'user_corrected')),
    linked_at TEXT NOT NULL,

    PRIMARY KEY (memory_id, source_message_id, source_type),
    FOREIGN KEY (memory_id)
        REFERENCES atomic_memories (id)
        ON DELETE CASCADE,
    FOREIGN KEY (source_message_id)
        REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);

INSERT INTO memory_evidence_v4 (
    memory_id, source_message_id, source_type, linked_at
)
SELECT memory_id, source_message_id, source_type, linked_at
FROM memory_evidence;

DROP TABLE memory_evidence;
ALTER TABLE memory_evidence_v4 RENAME TO memory_evidence;
CREATE INDEX idx_memory_evidence_source_message
    ON memory_evidence (source_message_id);

COMMIT;
"""


def initialize_schema(connection: Connection) -> None:
    """创建最新结构，或把 V1–V3 数据非破坏性升级到 V4。"""

    current_version = connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0]

    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            "数据库版本高于当前程序支持的版本："
            f"{current_version} > {SCHEMA_VERSION}"
        )

    if current_version == 0:
        connection.executescript(_LATEST_SCHEMA_SQL)
    else:
        if current_version == 1:
            # 先把 V1 的唯一来源转换成 V2 证据关系，
            # 后续重建记忆表时才能完全移除旧来源列。
            connection.executescript(_CREATE_V2_EVIDENCE_SQL)
            connection.executescript(_BACKFILL_V1_EVIDENCE_SQL)
            current_version = 2

        if current_version == 2:
            # 重建表期间临时关闭外键检查，完成后立即恢复并校验。
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")

            try:
                connection.executescript(_MIGRATE_V2_TO_V3_SQL)
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA foreign_keys = ON")

            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violations:
                raise RuntimeError(
                    "数据库升级后发现外键关系损坏："
                    f"{violations}"
                )

            current_version = 3

        if current_version == 3:
            # V4 只扩展来源枚举；SQLite 的 CHECK 约束必须通过重建表更新。
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            try:
                connection.executescript(_MIGRATE_V3_TO_V4_SQL)
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA foreign_keys = ON")

            violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if violations:
                raise RuntimeError(
                    "数据库升级后发现外键关系损坏："
                    f"{violations}"
                )

        connection.executescript(_LATEST_SCHEMA_SQL)

    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
