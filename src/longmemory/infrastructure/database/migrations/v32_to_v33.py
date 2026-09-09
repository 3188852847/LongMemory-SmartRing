"""V32 -> V33：增加不含正文的记忆质量复核事件。"""


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS memory_feedback_review_events (
    id TEXT PRIMARY KEY,
    feedback_source TEXT NOT NULL CHECK (feedback_source IN ('web_chat', 'round_screen')),
    feedback_target_id TEXT NOT NULL CHECK (length(trim(feedback_target_id)) BETWEEN 1 AND 200),
    feedback_revision INTEGER NOT NULL CHECK (feedback_revision >= 1),
    action TEXT NOT NULL CHECK (action IN ('resolve', 'dismiss', 'reopen')),
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'memory_corrected', 'retrieval_fixed', 'answer_behavior_fixed',
        'false_positive', 'not_memory_issue', 'other', 'needs_follow_up'
    )),
    review_revision INTEGER NOT NULL CHECK (review_revision >= 1),
    occurred_at TEXT NOT NULL,
    UNIQUE (feedback_source, feedback_target_id, feedback_revision, review_revision)
);
CREATE INDEX IF NOT EXISTS idx_memory_feedback_review_target
    ON memory_feedback_review_events
        (feedback_source, feedback_target_id, feedback_revision, review_revision DESC);
"""


def migrate(connection) -> None:
    """历史样本没有所有者复核结论，迁移后自然保持待处理。"""

    connection.executescript(MIGRATION_SQL)
