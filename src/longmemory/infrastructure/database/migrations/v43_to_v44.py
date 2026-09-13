"""V43 -> V44：新增不复制正文的日常 L1 提取尝试事件。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l1_extraction_events (
            id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('started','completed','failed')),
            outcome_code TEXT CHECK (outcome_code IN (
                'noop','added','reused','extraction_failed','persistence_failed'
            )),
            candidate_count INTEGER CHECK (candidate_count IS NULL OR candidate_count >= 0),
            added_count INTEGER CHECK (added_count IS NULL OR added_count >= 0),
            method_version TEXT NOT NULL CHECK (length(trim(method_version)) BETWEEN 1 AND 120),
            prompt_version TEXT CHECK (
                prompt_version IS NULL OR length(trim(prompt_version)) BETWEEN 1 AND 120
            ),
            preprocessor_version TEXT NOT NULL CHECK (
                length(trim(preprocessor_version)) BETWEEN 1 AND 120
            ),
            prompt_sha256 TEXT CHECK (
                prompt_sha256 IS NULL OR (
                    length(prompt_sha256)=64 AND prompt_sha256=lower(prompt_sha256)
                    AND prompt_sha256 NOT GLOB '*[^0-9a-f]*'
                )
            ),
            provider TEXT NOT NULL CHECK (length(trim(provider)) BETWEEN 1 AND 120),
            model TEXT NOT NULL CHECK (length(trim(model)) BETWEEN 1 AND 240),
            occurred_at TEXT NOT NULL,
            duration_ms REAL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            UNIQUE (attempt_id, phase),
            FOREIGN KEY (source_message_id)
                REFERENCES conversation_messages (id) ON DELETE CASCADE,
            CHECK (
                (phase='started' AND outcome_code IS NULL AND candidate_count IS NULL
                    AND added_count IS NULL AND duration_ms IS NULL)
                OR
                (phase IN ('completed','failed') AND outcome_code IS NOT NULL
                    AND candidate_count IS NOT NULL AND added_count IS NOT NULL
                    AND duration_ms IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_l1_extraction_events_source_time
            ON l1_extraction_events (source_message_id, occurred_at, id);
        CREATE INDEX IF NOT EXISTS idx_l1_extraction_events_attempt_phase
            ON l1_extraction_events (attempt_id, phase);
        """
    )
