"""V12→V13：记录每次自动整理所用的独立风险复核器版本。"""

from sqlite3 import Connection


def migrate(connection: Connection) -> None:
    """兼容保留旧运行；旧记录无法追溯复核器，因此字段保持 NULL。"""

    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(memory_consolidation_runs)"
        ).fetchall()
    }
    # 支持迁移事务中断后的安全重入，也兼容测试从当前定义还原旧版本的方式。
    if "risk_reviewer_version" in columns:
        return
    connection.execute(
        "ALTER TABLE memory_consolidation_runs ADD COLUMN risk_reviewer_version TEXT "
        "CHECK (risk_reviewer_version IS NULL OR "
        "length(trim(risk_reviewer_version)) BETWEEN 1 AND 120)"
    )
