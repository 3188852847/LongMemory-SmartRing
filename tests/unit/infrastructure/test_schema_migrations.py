"""数据库版本链的结构回归，不接触个人数据库。"""

import sqlite3

from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.migrations import MIGRATIONS
from longmemory.infrastructure.database.schema import initialize_schema


def test_migration_chain_is_contiguous_up_to_current_schema():
    """新增版本时不能漏掉任何一个来源版本的迁移步骤。"""

    assert tuple(MIGRATIONS) == tuple(range(1, SCHEMA_VERSION))
    assert len(set(MIGRATIONS.values())) == len(MIGRATIONS)


def test_v39_merge_history_is_not_guessed_during_v40_migration():
    """旧合并只有数量，V40 不能猜测具体来源并回填账本。"""

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)
    connection.execute("DROP TABLE l1_duplicate_merge_evidence")
    connection.execute("PRAGMA user_version = 39")
    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 40
    assert connection.execute(
        "SELECT count(*) FROM l1_duplicate_merge_evidence"
    ).fetchone()[0] == 0
