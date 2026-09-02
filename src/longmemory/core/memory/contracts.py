"""L1 原子记忆存储、提取和检索所需的抽象契约。"""

from typing import Protocol

from longmemory.core.common.identifiers import MemoryId
from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.models import AtomicMemory


class MemoryStore(Protocol):
    """核心层要求长期记忆存储提供的最小能力。"""

    def save(self, memory: AtomicMemory) -> None:
        """持久化一条原子记忆。"""
        ...

    def get(self, memory_id: MemoryId) -> AtomicMemory | None:
        """根据稳定标识符读取记忆；不存在时返回 None。"""
        ...

    def list_all(self) -> tuple[AtomicMemory, ...]:
        """按稳定顺序返回全部记忆。"""
        ...

    def delete(self, memory_id: MemoryId) -> bool:
        """删除指定记忆，返回是否确实删除了一条记录。"""
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