"""V46 -> V47：让 L2 影子复核保存精确场景支持集合。"""


def migrate(connection) -> None:
    candidate_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(l2_sufficiency_shadow_candidates)"
        )
    }
    if "content_characters" not in candidate_columns:
        connection.execute(
            "ALTER TABLE l2_sufficiency_shadow_candidates "
            "ADD COLUMN content_characters INTEGER "
            "CHECK (content_characters IS NULL OR content_characters >= 0)"
        )
    review_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(l2_sufficiency_shadow_review_events)"
        )
    }
    if "support_set_recorded" not in review_columns:
        connection.execute(
            "ALTER TABLE l2_sufficiency_shadow_review_events "
            "ADD COLUMN support_set_recorded INTEGER NOT NULL DEFAULT 0 "
            "CHECK (support_set_recorded IN (0,1))"
        )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS l2_sufficiency_shadow_review_supports (
            review_event_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            scenario_id TEXT NOT NULL,
            PRIMARY KEY (review_event_id, scenario_id),
            FOREIGN KEY (review_event_id)
                REFERENCES l2_sufficiency_shadow_review_events (id) ON DELETE CASCADE,
            FOREIGN KEY (user_message_id, scenario_id)
                REFERENCES l2_sufficiency_shadow_candidates (user_message_id, scenario_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_l2_shadow_review_support_scenario
            ON l2_sufficiency_shadow_review_supports (scenario_id, review_event_id);
        """
    )
