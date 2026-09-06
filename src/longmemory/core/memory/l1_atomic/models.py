"""L1 原子记忆及其来源关系领域模型。

本模块是 L1 的规范定义位置。旧的 ``core.memory.models`` 仅保留兼容
转发，避免已有调用方在架构校准期间被一次性打断。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId, MessageId


CURRENT_USER_SUBJECT_ID = MemorySubjectId("user:self")


class MemorySourceType(StrEnum):
    """来源证据对一条记忆声明的支持方式。"""

    USER_STATED = "user_stated"
    USER_CORRECTED = "user_corrected"


class MemoryOperationType(StrEnum):
    """记忆写入策略对一条候选事实作出的显式决定。"""

    ADD = "add"
    NOOP = "noop"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class MemoryEvidence:
    """一条 L0 消息对某条 L1 记忆提供的可追溯证据。"""

    memory_id: MemoryId
    source_message_id: MessageId
    source_type: MemorySourceType
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class AtomicMemory:
    """一条可以独立理解和检索的 L1 原子记忆。"""

    id: MemoryId
    subject_id: MemorySubjectId
    content: str
    recorded_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_id: MemoryId | None = None


@dataclass(frozen=True, slots=True)
class MemoryWriteOperation:
    """一次候选记忆处理产生的、可审计的写入结果。"""

    operation: MemoryOperationType
    memory: AtomicMemory
    evidence: MemoryEvidence
    superseded_memory_id: MemoryId | None = None

    def __post_init__(self) -> None:
        """保证取代操作与旧记忆 ID 始终成对出现。"""

        is_supersede = self.operation == MemoryOperationType.SUPERSEDE
        if is_supersede != (self.superseded_memory_id is not None):
            raise ValueError("只有 SUPERSEDE 操作必须提供 superseded_memory_id。")
