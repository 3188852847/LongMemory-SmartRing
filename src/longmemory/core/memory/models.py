"""L1 原子记忆及其来源关系领域模型。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.common.identifiers import MemoryId, MessageId


@dataclass(frozen=True, slots=True)
class AtomicMemory:
    """一条可以独立理解和检索的 L1 原子记忆。

    source_message_id 将规范化记忆指回原始 L0 消息，
    使记忆内容能够被检查、纠错和重新提取。
    """

    id: MemoryId
    content: str
    source_message_id: MessageId
    created_at: datetime