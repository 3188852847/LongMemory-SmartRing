"""V37 -> V38：追加 L1 质量候选的人工复核事件。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l1_quality_review_events (
            id TEXT PRIMARY KEY,
            left_memory_id TEXT NOT NULL,
            right_memory_id TEXT NOT NULL,
            detector_version TEXT NOT NULL CHECK (length(trim(detector_version)) BETWEEN 1 AND 120),
            candidate_kind TEXT NOT NULL CHECK (candidate_kind IN (
                'normalized_duplicate', 'lexical_near_duplicate', 'possible_conflict'
            )),
            action TEXT NOT NULL CHECK (action IN ('dismiss', 'reopen')),
            review_revision INTEGER NOT NULL CHECK (review_revision >= 1),
            occurred_at TEXT NOT NULL,
            CHECK (left_memory_id < right_memory_id),
            UNIQUE (left_memory_id, right_memory_id, detector_version, review_revision),
            FOREIGN KEY (left_memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
            FOREIGN KEY (right_memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l1_quality_review_pair
            ON l1_quality_review_events
                (left_memory_id, right_memory_id, detector_version, review_revision DESC);
        """
    )
