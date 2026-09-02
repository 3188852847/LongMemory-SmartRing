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
from longmemory.core.memory.models import (
    MemoryEvidence,
    MemoryOperationType,
    MemorySourceType,
    MemoryWriteOperation,
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
        candidate_memories = self._memory_extractor.extract(
            user_message
        )

        memory_operations = []

        for candidate_memory in candidate_memories:
            existing_memory = self._memory_store.find_by_content(
                candidate_memory.content,
                subject_id=candidate_memory.subject_id,
            )

            # 记忆声明与来源证据分开保存。同一句事实再次出现时，
            # 不创建重复 L1，但仍保留这次新的 L0 陈述作为证据。
            evidence = MemoryEvidence(
                memory_id=(
                    existing_memory.id
                    if existing_memory is not None
                    else candidate_memory.id
                ),
                source_message_id=user_message.id,
                source_type=MemorySourceType.USER_STATED,
                linked_at=candidate_memory.recorded_at,
            )

            if existing_memory is not None:
                self._memory_store.add_evidence(evidence)
                memory_operations.append(
                    MemoryWriteOperation(
                        operation=MemoryOperationType.NOOP,
                        memory=existing_memory,
                        evidence=evidence,
                    )
                )
                continue

            self._memory_store.save(candidate_memory, evidence)
            memory_operations.append(
                MemoryWriteOperation(
                    operation=MemoryOperationType.ADD,
                    memory=candidate_memory,
                    evidence=evidence,
                )
            )

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
            memory_operations=tuple(memory_operations),
            retrieved_memories=retrieved_memories,
            answer=answer,
        )
