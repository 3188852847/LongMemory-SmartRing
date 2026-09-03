"""独立记忆用例：保存用户输入、提取和检索；不生成回答。"""

from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4


from dataclasses import dataclass
from longmemory.core.memory.models import AtomicMemory
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


def _ignore_event(event: str, **fields: object) -> None:
    """默认不绑定任何日志设施；正式装配时注入审计接收函数。"""


@dataclass(frozen=True, slots=True)
class MemoryTurn:
    """本轮来源、写入操作及召回上下文，供 CLI 和外部语音框架共用。"""

    user_message: ConversationMessage
    memory_operations: tuple[MemoryWriteOperation, ...]
    retrieved_memories: tuple[AtomicMemory, ...]
    memory_context: str


class MemoryTurnService:
    """执行回答前的记忆流程，不依赖任何回答器或 Xiaozhi。"""

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        memory_store: MemoryStore,
        memory_extractor: MemoryExtractor,
        memory_retriever: MemoryRetriever,
        message_id_factory: Callable[[], MessageId] = _new_message_id,
        clock: Callable[[], datetime] = _utc_now,
        audit_sink: Callable[..., None] = _ignore_event,
        write_transaction: Callable = nullcontext,
    ) -> None:
        self._conversation_store = conversation_store
        self._memory_store = memory_store
        self._memory_extractor = memory_extractor
        self._memory_retriever = memory_retriever
        self._message_id_factory = message_id_factory
        self._clock = clock
        self._audit = audit_sink
        self._write_transaction = write_transaction

    def prepare(self, text: str) -> MemoryTurn:
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
        memory_operations = self.observe(user_message)
        retrieved_memories, memory_context = self.recall(text, turn_id=str(user_message.id))
        return MemoryTurn(
            user_message=user_message,
            memory_operations=memory_operations,
            retrieved_memories=retrieved_memories,
            memory_context=memory_context,
        )

    def observe(self, message: ConversationMessage) -> tuple[MemoryWriteOperation, ...]:
        """只接收一条已知来源消息，不生成回答，也不发起检索。

        实时入口仍由 prepare 创建 ID/时间；方法适配器可以传入历史原值。
        助手消息仅归档，不能因为回放历史而变成可靠的用户事实。
        """
        if not message.content.strip():
            raise EmptyMessageError("聊天消息不能为空。")
        # 装配层决定事务机制；记忆算法不依赖 SQLite。正式基线在同一
        # 写事务内完成 L0、查重、L1 和证据，失败时一起回滚。
        with self._write_transaction():
            return self._observe(message)

    def _observe(self, message: ConversationMessage) -> tuple[MemoryWriteOperation, ...]:
        self._conversation_store.save(message)
        if message.role != MessageRole.USER:
            return ()
        turn_id = str(message.id)
        self._audit("user_saved", turn_id=turn_id)

        # 从当前 L0 消息提取零条或多条 L1 记忆。
        candidate_memories = self._memory_extractor.extract(
            message
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
                source_message_id=message.id,
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

        for result in memory_operations:
            self._audit("memory_write", turn_id=turn_id,
                      memory_id=str(result.memory.id), operation=result.operation.value)
        self._audit("extraction_done", turn_id=turn_id, count=len(memory_operations))
        return tuple(memory_operations)

    def recall(self, text: str, *, turn_id: str) -> tuple[tuple[AtomicMemory, ...], str]:
        """只检索和构造上下文；查询不写 L0/L1，也不生成回答。

        这是独立召回能力，不等于平台已实现完整的冻结评估协议。
        prepare 仍按原有规则先 observe 再 recall，保持日常入口行为。
        """
        if not text.strip():
            raise EmptyMessageError("查询不能为空。")
        retrieved_memories = self._memory_retriever.retrieve(text)
        self._audit("memory_retrieved", turn_id=turn_id,
                  memory_ids=[str(memory.id) for memory in retrieved_memories])

        memory_context = build_memory_context(retrieved_memories)

        self._audit("context_built", turn_id=turn_id,
                  memory_ids=[str(memory.id) for memory in retrieved_memories])
        return retrieved_memories, memory_context
