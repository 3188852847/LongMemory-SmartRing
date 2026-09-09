"""V31 -> V32：为未来圆屏回答保存不含正文的召回证据索引。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS round_screen_retrieval_receipts (
    user_message_id TEXT PRIMARY KEY,
    FOREIGN KEY (user_message_id) REFERENCES round_screen_turns (user_message_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS round_screen_retrieval_evidence (
    user_message_id TEXT NOT NULL,
    layer TEXT NOT NULL CHECK (layer IN ('l1', 'l2', 'l3')),
    item_id TEXT NOT NULL CHECK (length(trim(item_id)) BETWEEN 1 AND 200),
    rank INTEGER NOT NULL CHECK (rank >= 1),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)
        AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    PRIMARY KEY (user_message_id, layer, rank),
    UNIQUE (user_message_id, layer, item_id),
    FOREIGN KEY (user_message_id) REFERENCES round_screen_turns (user_message_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_round_screen_retrieval_item
    ON round_screen_retrieval_evidence (layer, item_id);
"""


def migrate(connection) -> None:
    """旧回答只有数量，不能猜测当时召回条目，因此只创建空索引表。"""

    connection.executescript(MIGRATION_SQL)
