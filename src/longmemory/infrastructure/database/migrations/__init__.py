"""按来源版本注册的显式、连续 SQLite 迁移链。"""

from collections.abc import Callable
from sqlite3 import Connection

from longmemory.infrastructure.database.migrations.v1_to_v2 import migrate as v1_to_v2
from longmemory.infrastructure.database.migrations.v2_to_v3 import migrate as v2_to_v3
from longmemory.infrastructure.database.migrations.v3_to_v4 import migrate as v3_to_v4
from longmemory.infrastructure.database.migrations.v4_to_v5 import migrate as v4_to_v5
from longmemory.infrastructure.database.migrations.v5_to_v6 import migrate as v5_to_v6
from longmemory.infrastructure.database.migrations.v6_to_v7 import migrate as v6_to_v7
from longmemory.infrastructure.database.migrations.v7_to_v8 import migrate as v7_to_v8
from longmemory.infrastructure.database.migrations.v8_to_v9 import migrate as v8_to_v9
from longmemory.infrastructure.database.migrations.v9_to_v10 import migrate as v9_to_v10
from longmemory.infrastructure.database.migrations.v10_to_v11 import migrate as v10_to_v11
from longmemory.infrastructure.database.migrations.v11_to_v12 import migrate as v11_to_v12
from longmemory.infrastructure.database.migrations.v12_to_v13 import migrate as v12_to_v13
from longmemory.infrastructure.database.migrations.v13_to_v14 import migrate as v13_to_v14
from longmemory.infrastructure.database.migrations.v14_to_v15 import migrate as v14_to_v15
from longmemory.infrastructure.database.migrations.v15_to_v16 import migrate as v15_to_v16
from longmemory.infrastructure.database.migrations.v16_to_v17 import migrate as v16_to_v17
from longmemory.infrastructure.database.migrations.v17_to_v18 import migrate as v17_to_v18
from longmemory.infrastructure.database.migrations.v18_to_v19 import migrate as v18_to_v19

Migration = Callable[[Connection], None]
MIGRATIONS: dict[int, Migration] = {
    1: v1_to_v2,
    2: v2_to_v3,
    3: v3_to_v4,
    4: v4_to_v5,
    5: v5_to_v6,
    6: v6_to_v7,
    7: v7_to_v8,
    8: v8_to_v9,
    9: v9_to_v10,
    10: v10_to_v11,
    11: v11_to_v12,
    12: v12_to_v13,
    13: v13_to_v14,
    14: v14_to_v15,
    15: v15_to_v16,
    16: v16_to_v17,
    17: v17_to_v18,
    18: v18_to_v19,
}

__all__ = ["MIGRATIONS", "Migration"]
