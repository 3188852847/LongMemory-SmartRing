"""按来源版本注册的显式、连续 SQLite 迁移链。"""

from collections.abc import Callable
from sqlite3 import Connection

from longmemory.infrastructure.database.migrations.v1_to_v2 import migrate as v1_to_v2
from longmemory.infrastructure.database.migrations.v2_to_v3 import migrate as v2_to_v3
from longmemory.infrastructure.database.migrations.v3_to_v4 import migrate as v3_to_v4

Migration = Callable[[Connection], None]
MIGRATIONS: dict[int, Migration] = {1: v1_to_v2, 2: v2_to_v3, 3: v3_to_v4}

__all__ = ["MIGRATIONS", "Migration"]
