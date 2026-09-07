"""SQLite 结构入口：创建当前版本，或按连续迁移链升级旧版本。"""

from sqlite3 import Connection

from longmemory.infrastructure.database.definition import (
    LATEST_SCHEMA_SQL,
    SCHEMA_VERSION,
)
from longmemory.infrastructure.database.migrations import MIGRATIONS


def initialize_schema(connection: Connection) -> None:
    """创建 V26 结构，或把 V1–V25 数据非破坏性升级到 V26。"""

    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            "数据库版本高于当前程序支持的版本："
            f"{current_version} > {SCHEMA_VERSION}"
        )

    if current_version == 0:
        connection.executescript(LATEST_SCHEMA_SQL)
    else:
        while current_version < SCHEMA_VERSION:
            migration = MIGRATIONS.get(current_version)
            if migration is None:
                raise RuntimeError(f"缺少从 V{current_version} 开始的数据库迁移。")
            migration(connection)
            current_version += 1
        # 历史迁移只负责数据变化；幂等执行当前定义可补齐当前索引。
        connection.executescript(LATEST_SCHEMA_SQL)

    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


__all__ = ["SCHEMA_VERSION", "initialize_schema"]
