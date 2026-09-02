"""一轮文本聊天用例的输入输出数据结构。"""

from dataclasses import dataclass

from longmemory.core.conversation.models import ConversationMessage
from longmemory.core.memory.models import AtomicMemory


@dataclass(frozen=True, slots=True)
class ChatResult:
    """一次聊天调用产生的可检查结果。

    除了最终回答，还显式暴露本轮保存和检索到的记忆，
    便于调试长程记忆闭环，而不是只能观察模型最后说了什么。
    """

    user_message: ConversationMessage
    saved_memories: tuple[AtomicMemory, ...]
    retrieved_memories: tuple[AtomicMemory, ...]
    answer: str