"""V49 -> V50：增加默认关闭的受约束动态问候开关。"""


def migrate(connection) -> None:
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(proactive_policy_settings)"
        )
    }
    if "dynamic_greeting_enabled" in columns:
        return
    connection.execute(
        "ALTER TABLE proactive_policy_settings ADD COLUMN "
        "dynamic_greeting_enabled INTEGER NOT NULL DEFAULT 0 "
        "CHECK (dynamic_greeting_enabled IN (0,1))"
    )
