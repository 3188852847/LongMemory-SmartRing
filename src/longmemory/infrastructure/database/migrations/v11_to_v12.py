"""V11→V12：让 L2 自动接受拥有独立策略身份与理由。"""

from sqlite3 import Connection


_SQL = """
CREATE TABLE scenario_reviews_v12 (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reviewer_type TEXT NOT NULL CHECK (reviewer_type IN ('user', 'policy')),
    reviewed_at TEXT NOT NULL,
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 1),
    policy_version TEXT,
    decision_reason TEXT,
    CHECK (
        (reviewer_type = 'user' AND policy_version IS NULL AND decision_reason IS NULL)
        OR
        (reviewer_type = 'policy' AND decision = 'accepted'
            AND length(trim(policy_version)) BETWEEN 1 AND 120
            AND length(trim(decision_reason)) BETWEEN 1 AND 120)
    ),
    FOREIGN KEY (scenario_id) REFERENCES scenario_memories (id) ON DELETE CASCADE
);
INSERT INTO scenario_reviews_v12 (
    id,scenario_id,decision,reviewer_type,reviewed_at,scenario_revision,
    policy_version,decision_reason
)
SELECT id,scenario_id,decision,reviewer_type,reviewed_at,scenario_revision,NULL,NULL
FROM scenario_reviews;
DROP TABLE scenario_reviews;
ALTER TABLE scenario_reviews_v12 RENAME TO scenario_reviews;
"""


def migrate(connection: Connection) -> None:
    """保留 V11 人工复核，只增加可为空的策略审计字段。"""

    connection.executescript(_SQL)
