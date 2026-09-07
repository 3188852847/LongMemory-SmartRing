"""V17→V18：默认关闭记忆话题投递，并给主动消息保存素材来源。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    policy_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(proactive_policy_settings)"
        )
    }
    if "topic_enabled" not in policy_columns:
        connection.execute(
            "ALTER TABLE proactive_policy_settings ADD COLUMN topic_enabled "
            "INTEGER NOT NULL DEFAULT 0 CHECK (topic_enabled IN (0,1))"
        )
    outreach_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(proactive_outreach)")
    }
    if "topic_seed_id" not in outreach_columns:
        connection.execute(
            "ALTER TABLE proactive_outreach ADD COLUMN topic_seed_id TEXT "
            "REFERENCES proactive_topic_seeds(id) ON DELETE RESTRICT"
        )
    if "topic_seed_revision" not in outreach_columns:
        connection.execute(
            "ALTER TABLE proactive_outreach ADD COLUMN topic_seed_revision INTEGER "
            "CHECK (topic_seed_revision IS NULL OR topic_seed_revision >= 1)"
        )
