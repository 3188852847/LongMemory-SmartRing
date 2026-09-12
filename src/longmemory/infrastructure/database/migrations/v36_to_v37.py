"""V36 -> V37：保留日常圆屏召回策略与可校准的原始分数。"""


def migrate(connection) -> None:
    receipt_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(round_screen_retrieval_receipts)"
        )
    }
    if "retrieval_strategy" not in receipt_columns:
        connection.execute(
            "ALTER TABLE round_screen_retrieval_receipts ADD COLUMN retrieval_strategy "
            "TEXT CHECK (retrieval_strategy IS NULL OR "
            "length(trim(retrieval_strategy)) BETWEEN 1 AND 240)"
        )
    evidence_columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(round_screen_retrieval_evidence)"
        )
    }
    additions = {
        "keyword_score": "INTEGER CHECK (keyword_score IS NULL OR keyword_score >= 0)",
        "dense_score": "REAL",
        "fused_score": "REAL",
    }
    for name, definition in additions.items():
        if name not in evidence_columns:
            connection.execute(
                f"ALTER TABLE round_screen_retrieval_evidence ADD COLUMN {name} {definition}"
            )
