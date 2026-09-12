"""V41 -> V42：追加不改变回答的 L2 证据充分性影子审计。"""


def migrate(connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l2_sufficiency_shadow_runs (
            user_message_id TEXT PRIMARY KEY,
            retrieval_strategy TEXT NOT NULL CHECK (
                length(trim(retrieval_strategy)) BETWEEN 1 AND 120
            ),
            reviewer_version TEXT NOT NULL CHECK (
                length(trim(reviewer_version)) BETWEEN 1 AND 120
            ),
            prompt_sha256 TEXT NOT NULL CHECK (
                length(prompt_sha256)=64 AND prompt_sha256=lower(prompt_sha256)
                AND prompt_sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            provider TEXT NOT NULL CHECK (length(trim(provider)) BETWEEN 1 AND 80),
            model TEXT NOT NULL CHECK (length(trim(model)) BETWEEN 1 AND 160),
            status TEXT NOT NULL CHECK (status IN ('pending','completed','failed')),
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            error_code TEXT CHECK (
                error_code IS NULL OR length(trim(error_code)) BETWEEN 1 AND 120
            ),
            CHECK (
                (status='pending' AND completed_at IS NULL AND error_code IS NULL)
                OR (status='completed' AND completed_at IS NOT NULL AND error_code IS NULL)
                OR (status='failed' AND completed_at IS NOT NULL AND error_code IS NOT NULL)
            ),
            FOREIGN KEY (user_message_id) REFERENCES conversation_messages (id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_l2_sufficiency_shadow_status_time
            ON l2_sufficiency_shadow_runs (status, requested_at DESC);

        CREATE TABLE IF NOT EXISTS l2_sufficiency_shadow_candidates (
            user_message_id TEXT NOT NULL,
            scenario_id TEXT NOT NULL CHECK (length(trim(scenario_id)) BETWEEN 1 AND 200),
            rank INTEGER NOT NULL CHECK (rank >= 1),
            content_sha256 TEXT NOT NULL CHECK (
                length(content_sha256)=64 AND content_sha256=lower(content_sha256)
                AND content_sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            keyword_score INTEGER CHECK (keyword_score IS NULL OR keyword_score >= 0),
            supports_answer INTEGER CHECK (supports_answer IN (0,1)),
            reason_code TEXT CHECK (reason_code IN (
                'direct_support','partial_support','topic_only',
                'missing_attribute','irrelevant','conflicting_evidence'
            )),
            PRIMARY KEY (user_message_id, rank),
            UNIQUE (user_message_id, scenario_id),
            CHECK (
                (supports_answer IS NULL AND reason_code IS NULL)
                OR (supports_answer IS NOT NULL AND reason_code IS NOT NULL)
            ),
            FOREIGN KEY (user_message_id)
                REFERENCES l2_sufficiency_shadow_runs (user_message_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l2_sufficiency_shadow_scenario
            ON l2_sufficiency_shadow_candidates (scenario_id, user_message_id);
        """
    )
