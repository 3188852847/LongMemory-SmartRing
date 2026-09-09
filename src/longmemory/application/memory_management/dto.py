"""记忆查看和删除用例的输入输出结构。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.l1_atomic.models import AtomicMemory, MemoryEvidence


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


@dataclass(frozen=True, slots=True)
class MemoryCorrectionResult:
    """一次人工纠正产生的新旧记忆与审计来源。"""

    old_memory: AtomicMemory
    new_memory: AtomicMemory
    source_message: ConversationMessage
    evidence: MemoryEvidence


@dataclass(frozen=True, slots=True)
class MemoryChangeResult:
    """一次事实变化产生的新旧记忆、现实生效时间与审计来源。"""

    old_memory: AtomicMemory
    new_memory: AtomicMemory
    source_message: ConversationMessage
    evidence: MemoryEvidence
    effective_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryPromotionResult:
    """把既有 L0 显式补为 L1 后的结果，不复制原始消息。"""

    memory: AtomicMemory
    source_message: ConversationMessage
    evidence: MemoryEvidence
    created_new_memory: bool
