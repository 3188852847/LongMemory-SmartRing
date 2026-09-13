"""V47 -> V48：保留圆屏回答当时的历史事实角色与有效区间。"""


def migrate(connection) -> None:
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(round_screen_retrieval_evidence)"
        )
    }
    additions = {
        "temporal_role": (
            "TEXT CHECK (temporal_role IS NULL OR "
            "(layer = 'l1' AND temporal_role = 'historical'))"
        ),
        "valid_from": "TEXT",
        "valid_to": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE round_screen_retrieval_evidence "
                f"ADD COLUMN {name} {definition}"
            )
