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
from longmemory.infrastructure.database.migrations.v19_to_v20 import migrate as v19_to_v20
from longmemory.infrastructure.database.migrations.v20_to_v21 import migrate as v20_to_v21
from longmemory.infrastructure.database.migrations.v21_to_v22 import migrate as v21_to_v22
from longmemory.infrastructure.database.migrations.v22_to_v23 import migrate as v22_to_v23
from longmemory.infrastructure.database.migrations.v23_to_v24 import migrate as v23_to_v24
from longmemory.infrastructure.database.migrations.v24_to_v25 import migrate as v24_to_v25
from longmemory.infrastructure.database.migrations.v25_to_v26 import migrate as v25_to_v26
from longmemory.infrastructure.database.migrations.v26_to_v27 import migrate as v26_to_v27
from longmemory.infrastructure.database.migrations.v27_to_v28 import migrate as v27_to_v28
from longmemory.infrastructure.database.migrations.v28_to_v29 import migrate as v28_to_v29
from longmemory.infrastructure.database.migrations.v29_to_v30 import migrate as v29_to_v30
from longmemory.infrastructure.database.migrations.v30_to_v31 import migrate as v30_to_v31
from longmemory.infrastructure.database.migrations.v31_to_v32 import migrate as v31_to_v32
from longmemory.infrastructure.database.migrations.v32_to_v33 import migrate as v32_to_v33
from longmemory.infrastructure.database.migrations.v33_to_v34 import migrate as v33_to_v34
from longmemory.infrastructure.database.migrations.v34_to_v35 import migrate as v34_to_v35
from longmemory.infrastructure.database.migrations.v35_to_v36 import migrate as v35_to_v36

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
    19: v19_to_v20,
    20: v20_to_v21,
    21: v21_to_v22,
    22: v22_to_v23,
    23: v23_to_v24,
    24: v24_to_v25,
    25: v25_to_v26,
    26: v26_to_v27,
    27: v27_to_v28,
    28: v28_to_v29,
    29: v29_to_v30,
    30: v30_to_v31,
    31: v31_to_v32,
    32: v32_to_v33,
    33: v33_to_v34,
    34: v34_to_v35,
    35: v35_to_v36,
}

__all__ = ["MIGRATIONS", "Migration"]
