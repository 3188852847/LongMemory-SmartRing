"""兼容入口：L1 模型已迁移到 :mod:`core.memory.l1_atomic`。

已有插件和脚本可以继续使用旧导入路径；新代码应从 ``l1_atomic`` 导入。
这里直接转发同一批类，而不是复制定义，因此不会产生两套类型身份。
"""

from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    CURRENT_USER_SUBJECT_ID,
    MemoryEvidence,
    MemoryOperationType,
    MemorySourceType,
    MemoryWriteOperation,
)

__all__ = [
    "AtomicMemory",
    "CURRENT_USER_SUBJECT_ID",
    "MemoryEvidence",
    "MemoryOperationType",
    "MemorySourceType",
    "MemoryWriteOperation",
]
