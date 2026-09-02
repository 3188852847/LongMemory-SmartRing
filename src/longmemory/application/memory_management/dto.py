"""记忆查看和删除用例的输入输出结构。"""

from dataclasses import dataclass

from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.models import AtomicMemory, MemoryEvidence


@dataclass(frozen=True, slots=True)
class MemoryEvidenceDetails:
    """一条来源证据以及它指向的 L0 原始消息。"""

    evidence: MemoryEvidence
    source_message: ConversationMessage | None


@dataclass(frozen=True, slots=True)
class MemoryDetails:
    """一条 L1 记忆及其全部 L0 原始来源。

    正常 SQLite 数据中，每条证据的 source_message 应当存在。
    这里仍允许为 None，是为了让管理界面能够暴露异常数据，
    而不是在数据库损坏或迁移错误时完全无法查看记忆。
    """

    memory: AtomicMemory
    sources: tuple[MemoryEvidenceDetails, ...]
