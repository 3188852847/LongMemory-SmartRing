"""V29 -> V30：保存圆屏回答与其用户轮次的最小关联。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS round_screen_turns (
    user_message_id TEXT PRIMARY KEY,
    assistant_message_id TEXT NOT NULL UNIQUE,
    retrieved_l1_count INTEGER NOT NULL CHECK (retrieved_l1_count >= 0),
    retrieved_l2_count INTEGER NOT NULL CHECK (retrieved_l2_count >= 0),
    retrieved_l3_count INTEGER NOT NULL CHECK (retrieved_l3_count >= 0),
    completed_at TEXT NOT NULL,
    FOREIGN KEY (user_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT,
    FOREIGN KEY (assistant_message_id) REFERENCES conversation_messages (id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_round_screen_turns_completed
    ON round_screen_turns (completed_at DESC, user_message_id DESC);
"""


def migrate(connection) -> None:
    """只新增空关联表；不能从旧对话时间猜测历史问答配对。"""

    connection.executescript(MIGRATION_SQL)
