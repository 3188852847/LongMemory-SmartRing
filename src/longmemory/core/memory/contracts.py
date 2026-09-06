"""L1 原子记忆存储、提取和检索所需的抽象契约。"""

from typing import Protocol
from datetime import datetime

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.models import AtomicMemory, MemoryEvidence


class MemoryStore(Protocol):
    """核心层要求长期记忆存储提供的最小能力。"""

    def save(
        self,
        memory: AtomicMemory,
        evidence: MemoryEvidence,
    ) -> None:
        """在同一事务中持久化原子记忆及其首条来源证据。"""
        ...

    def add_evidence(self, evidence: MemoryEvidence) -> bool:
        """给已有记忆关联来源；已经关联时返回 False。"""
        ...

    def list_evidence(
        self,
        memory_id: MemoryId,
    ) -> tuple[MemoryEvidence, ...]:
        """按稳定顺序返回指定记忆的全部来源证据。"""
        ...

    def get(self, memory_id: MemoryId) -> AtomicMemory | None:
        """根据稳定标识符读取记忆；不存在时返回 None。"""
        ...

    def find_by_content(
        self,
        content: str,
        *,
        subject_id: MemorySubjectId,
    ) -> AtomicMemory | None:
        """在指定主体的当前有效记忆中查找完全相同的内容。"""
        ...

    def list_all(self) -> tuple[AtomicMemory, ...]:
        """按稳定顺序返回全部记忆。"""
        ...

    def list_active(self) -> tuple[AtomicMemory, ...]:
        """按稳定顺序返回尚未退出当前有效集合的记忆。"""
        ...

    def delete(self, memory_id: MemoryId) -> bool:
        """删除指定记忆，返回是否确实删除了一条记录。"""
        ...

    def retire_as_superseded(
        self,
        memory_id: MemoryId,
        *,
        superseded_by_id: MemoryId,
        retired_at: datetime,
        valid_to: datetime | None = None,
    ) -> bool:
        """把仍有效的旧记忆标记为由新记忆取代。

        valid_to 只在“事实后来变化”时填写；人工纠错不能借它冒充
        旧错误事实曾经真实成立。
        """
        ...


class MemoryExtractor(Protocol):
    """聊天用例所依赖的记忆提取接口。"""

    def extract(
        self,
        message: ConversationMessage,
    ) -> tuple[AtomicMemory, ...]:
        """从一条 L0 消息中生成零条或多条 L1 原子记忆。"""
        ...


class MemoryRetriever(Protocol):
    """聊天用例所依赖的记忆检索接口。"""

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[AtomicMemory, ...]:
        """返回与当前问题最相关的若干条记忆。"""
        ...
