"""SQLite 连接和生命周期管理。"""

from pathlib import Path
from sqlite3 import Connection, Row, connect


def open_database(database_path: Path) -> Connection:
    """打开 SQLite 数据库并启用项目需要的连接配置。

    调用方拥有返回的连接，并负责在使用结束后调用 close()。
    """

    # 测试中的临时目录通常已经存在，但正式运行时数据库目录
    # 可能尚未创建，因此在连接前确保父目录存在。
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = connect(database_path)

    # 让查询结果可以通过 row["column_name"] 读取，
    # 避免代码依赖 SELECT 字段的排列顺序。
    connection.row_factory = Row

    # SQLite 默认不会主动执行外键约束，需要每条连接显式开启。
    connection.execute("PRAGMA foreign_keys = ON")

    return connection