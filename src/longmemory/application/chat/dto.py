"""一轮文本聊天用例的输入输出数据结构。"""

from dataclasses import dataclass

from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    MemoryOperationType,
    MemoryWriteOperation,
)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """一次聊天调用产生的可检查结果。

    除了最终回答，还显式暴露本轮保存和检索到的记忆，
    便于调试长程记忆闭环，而不是只能观察模型最后说了什么。
    """

    user_message: ConversationMessage
    assistant_message: ConversationMessage
    memory_operations: tuple[MemoryWriteOperation, ...]
    retrieved_memories: tuple[AtomicMemory, ...]
    answer: str

    @property
    def saved_memories(self) -> tuple[AtomicMemory, ...]:
        """返回本轮通过 ADD 新建的记忆，供调用方直接检查。"""

        return tuple(
            result.memory
            for result in self.memory_operations
            if result.operation == MemoryOperationType.ADD
        )

    @property
    def reused_memories(self) -> tuple[AtomicMemory, ...]:
        """返回本轮通过 NOOP 复用的已有记忆。"""

        return tuple(
            result.memory
            for result in self.memory_operations
            if result.operation == MemoryOperationType.NOOP
        )
