"""V30 -> V31：新增圆屏明确记忆质量反馈事件。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS round_screen_memory_feedback_events (
    id TEXT PRIMARY KEY,
    target_user_message_id TEXT NOT NULL,
    feedback_message_id TEXT NOT NULL UNIQUE,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('recall_miss', 'wrong_memory')),
    evidence_kind TEXT NOT NULL CHECK (evidence_kind = 'explicit_round_screen_statement'),
    interpreter_version TEXT NOT NULL CHECK (length(trim(interpreter_version)) BETWEEN 1 AND 120),
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (target_user_message_id) REFERENCES round_screen_turns (user_message_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (feedback_message_id) REFERENCES conversation_messages (id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_round_screen_memory_feedback_target
    ON round_screen_memory_feedback_events
        (target_user_message_id, occurred_at DESC, id DESC);
"""


def migrate(connection) -> None:
    """只新增空事件表；不能从旧对话猜测用户是否表达过反馈。"""

    connection.executescript(MIGRATION_SQL)
