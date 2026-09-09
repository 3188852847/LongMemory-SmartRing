"""V35 -> V36：记录跟进候选的形成方式与直接对话来源。"""


def migrate(connection) -> None:
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(companion_follow_up_candidates)"
        )
    }
    if "creation_kind" not in columns:
        connection.execute(
            "ALTER TABLE companion_follow_up_candidates ADD COLUMN creation_kind TEXT "
            "NOT NULL DEFAULT 'owner_created' CHECK (creation_kind IN "
            "('owner_created','explicit_conversation_request'))"
        )
    if "source_message_id" not in columns:
        connection.execute(
            "ALTER TABLE companion_follow_up_candidates ADD COLUMN source_message_id TEXT "
            "REFERENCES conversation_messages(id) ON DELETE SET NULL"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_follow_up_source_message "
        "ON companion_follow_up_candidates(source_message_id) "
        "WHERE source_message_id IS NOT NULL"
    )
