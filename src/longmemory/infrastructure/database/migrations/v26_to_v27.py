"""V26 -> V27：为主动问候投影增加结构化策略运行来源。"""


def migrate(connection) -> None:
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(proactive_outreach)")
    }
    additions = (
        (
            "strategy_version_id",
            "TEXT REFERENCES companion_absence_strategy_versions(id)",
        ),
        (
            "strategy_selection_revision",
            "INTEGER CHECK (strategy_selection_revision IS NULL "
            "OR strategy_selection_revision >= 1)",
        ),
        ("strategy_evaluated_local_date", "TEXT"),
    )
    for name, declaration in additions:
        if name not in columns:
            connection.execute(
                f"ALTER TABLE proactive_outreach ADD COLUMN {name} {declaration}"
            )
