"""编排保存、提取、检索、上下文构建和回答。"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from longmemory.application.chat.contracts import AnswerGenerator
from longmemory.application.chat.dto import ChatResult
from longmemory.core.common.exceptions import EmptyMessageError
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.contracts import (
    MemoryExtractor,
    MemoryRetriever,
    MemoryStore,
)
from longmemory.core.memory.retrieval.context_builder import (
    build_memory_context,
)


def _new_message_id() -> MessageId:
    """为正式运行生成全局唯一的 L0 消息 ID。"""

    return MessageId(str(uuid4()))


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


class ChatService:
    """执行一次文本聊天所需的完整应用流程。"""

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        memory_store: MemoryStore,
        memory_extractor: MemoryExtractor,
        memory_retriever: MemoryRetriever,
        answer_generator: AnswerGenerator,
        message_id_factory: Callable[[], MessageId] = _new_message_id,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._conversation_store = conversation_store
        self._memory_store = memory_store
        self._memory_extractor = memory_extractor
        self._memory_retriever = memory_retriever
        self._answer_generator = answer_generator
        self._message_id_factory = message_id_factory
        self._clock = clock

    def chat(self, text: str) -> ChatResult:
        """处理一条用户输入并返回可检查的完整结果。"""

        if not text.strip():
            raise EmptyMessageError("聊天消息不能为空。")

        # L0 保存原始输入。这里只用 strip() 判断是否为空，
        # 不修改实际保存的文本，便于以后审计原始输入。
        user_message = ConversationMessage(
            id=self._message_id_factory(),
            role=MessageRole.USER,
            content=text,
            created_at=self._clock(),
        )
        self._conversation_store.save(user_message)

        # 从当前 L0 消息提取零条或多条 L1 记忆。
        saved_memories = self._memory_extractor.extract(user_message)

        for memory in saved_memories:
            self._memory_store.save(memory)

        # 当前基线在写入后执行检索，因此本轮刚写入的记忆
        # 也可能参与本轮回答。
        retrieved_memories = self._memory_retriever.retrieve(text)

        memory_context = build_memory_context(retrieved_memories)

        answer = self._answer_generator.generate(
            query=text,
            memory_context=memory_context,
        )

        return ChatResult(
            user_message=user_message,
            saved_memories=saved_memories,
            retrieved_memories=retrieved_memories,
            answer=answer,
        )