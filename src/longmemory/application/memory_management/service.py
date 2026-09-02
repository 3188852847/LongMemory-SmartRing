"""编排记忆查看、删除和来源追踪。"""

from longmemory.application.memory_management.dto import (
    MemoryDetails,
    MemoryEvidenceDetails,
)
from longmemory.core.common.identifiers import MemoryId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.memory.contracts import MemoryStore
from longmemory.core.memory.models import AtomicMemory


class MemoryManagementService:
    """提供不依赖 CLI 和数据库实现的记忆管理用例。"""

    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        conversation_store: ConversationStore,
    ) -> None:
        self._memory_store = memory_store
        self._conversation_store = conversation_store

    def list_memories(self) -> tuple[MemoryDetails, ...]:
        """列出全部记忆，并附带各自的 L0 来源。"""

        return tuple(
            self._build_details(memory)
            for memory in self._memory_store.list_all()
        )

    def get_memory(
        self,
        memory_id: MemoryId,
    ) -> MemoryDetails | None:
        """根据 ID 查看一条记忆及其来源。"""

        memory = self._memory_store.get(memory_id)

        if memory is None:
            return None

        return self._build_details(memory)

    def delete_memory(self, memory_id: MemoryId) -> bool:
        """删除一条 L1 记忆，但保留其 L0 原始来源。

        返回 True 表示确实删除了一条记忆；
        返回 False 表示该 ID 原本就不存在。
        """

        return self._memory_store.delete(memory_id)

    def _build_details(
        self,
        memory: AtomicMemory,
    ) -> MemoryDetails:
        """组装一条记忆及其原始来源。"""

        sources = tuple(
            MemoryEvidenceDetails(
                evidence=evidence,
                source_message=self._conversation_store.get(
                    evidence.source_message_id
                ),
            )
            for evidence in self._memory_store.list_evidence(memory.id)
        )

        return MemoryDetails(
            memory=memory,
            sources=sources,
        )
