"""记忆提取/检索契约，以及旧 L1 Store 导入的兼容入口。"""

from typing import Protocol

from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.l1_atomic.models import AtomicMemory


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


__all__ = ["MemoryExtractor", "MemoryRetriever", "MemoryStore"]
