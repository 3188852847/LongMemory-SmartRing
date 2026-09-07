"""V15→V16：为显式定时问候增加默认关闭的配置。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(proactive_policy_settings)"
        )
    }
    additions = {
        "automatic_enabled": (
            "INTEGER NOT NULL DEFAULT 0 CHECK (automatic_enabled IN (0,1))"
        ),
        "scheduled_minute": (
            "INTEGER NOT NULL DEFAULT 780 CHECK (scheduled_minute BETWEEN 0 AND 1439)"
        ),
        "greeting_text": (
            "TEXT NOT NULL DEFAULT '下午好，今天过得怎么样？' "
            "CHECK (length(trim(greeting_text)) BETWEEN 1 AND 80)"
        ),
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE proactive_policy_settings ADD COLUMN {name} {definition}"
            )
    connection.execute(
        "UPDATE proactive_policy_settings "
        "SET scheduled_minute=allowed_start_minute,"
        "policy_version='proactive-contact-policy-v2'"
    )
