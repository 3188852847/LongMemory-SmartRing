"""数据库版本链的结构回归，不接触个人数据库。"""

from longmemory.infrastructure.database.definition import SCHEMA_VERSION
from longmemory.infrastructure.database.migrations import MIGRATIONS


def test_migration_chain_is_contiguous_up_to_current_schema():
    """新增版本时不能漏掉任何一个来源版本的迁移步骤。"""

    assert tuple(MIGRATIONS) == tuple(range(1, SCHEMA_VERSION))
    assert len(set(MIGRATIONS.values())) == len(MIGRATIONS)
