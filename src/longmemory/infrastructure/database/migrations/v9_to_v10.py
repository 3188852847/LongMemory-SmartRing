"""V9→V10：让 L3 自动接受拥有独立审计身份，而不是冒充用户。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE persona_reviews_v10 (
    id TEXT PRIMARY KEY,
    persona_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user', 'policy')),
    reviewed_at TEXT NOT NULL,
    persona_revision INTEGER NOT NULL CHECK (persona_revision >= 1),
    policy_version TEXT,
    decision_reason TEXT,
    CHECK (
        (reviewer_type = 'user' AND policy_version IS NULL AND decision_reason IS NULL)
        OR
        (reviewer_type = 'policy' AND decision = 'accepted'
            AND length(trim(policy_version)) BETWEEN 1 AND 120
            AND length(trim(decision_reason)) BETWEEN 1 AND 120)
    ),
    FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
);
INSERT INTO persona_reviews_v10 (
    id, persona_id, decision, reviewer_type, reviewed_at, persona_revision,
    policy_version, decision_reason
)
SELECT id, persona_id, decision, reviewer_type, reviewed_at, persona_revision, NULL, NULL
FROM persona_reviews;
DROP TABLE persona_reviews;
ALTER TABLE persona_reviews_v10 RENAME TO persona_reviews;
"""


def migrate(connection: Connection) -> None:
    """保留所有 V9 人工复核，只增加可为空的策略审计字段。"""

    connection.executescript(_SQL)
