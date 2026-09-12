"""V38 -> V39：记录经所有者确认的 L1 重复合并。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l1_duplicate_merge_events (
            id TEXT PRIMARY KEY,
            kept_memory_id TEXT NOT NULL,
            retired_memory_id TEXT NOT NULL UNIQUE,
            detector_version TEXT NOT NULL CHECK (length(trim(detector_version)) BETWEEN 1 AND 120),
            candidate_kind TEXT NOT NULL CHECK (candidate_kind IN (
                'normalized_duplicate', 'lexical_near_duplicate'
            )),
            copied_evidence_count INTEGER NOT NULL CHECK (copied_evidence_count >= 0),
            merged_at TEXT NOT NULL,
            CHECK (kept_memory_id <> retired_memory_id),
            FOREIGN KEY (kept_memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE,
            FOREIGN KEY (retired_memory_id) REFERENCES atomic_memories (id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l1_duplicate_merge_kept
            ON l1_duplicate_merge_events (kept_memory_id, merged_at DESC, id DESC);
        """
    )
