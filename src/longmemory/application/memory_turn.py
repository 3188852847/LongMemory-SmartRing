"""独立记忆用例：保存用户输入、提取和检索；不生成回答。"""

from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4


from dataclasses import dataclass
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.common.exceptions import EmptyMessageError
from longmemory.core.companion.contracts import (
    InteractionOutcomeObserver,
    UserInitiatedInteractionObserver,
)
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.contracts import ConversationStore
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.contracts import (
    MemoryExtractor,
    MemoryRetriever,
)
from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.retrieval.context_builder import (
    build_memory_context,
)
from longmemory.core.memory.retrieval.service import is_memory_effective
from longmemory.core.memory.quality.l1_candidates import (
    canonicalize_l1_for_exact_dedup,
)
from longmemory.core.memory.l1_atomic.models import (
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
        interaction_outcome_observer: InteractionOutcomeObserver | None = None,
        user_initiated_interaction_observer: (
            UserInitiatedInteractionObserver | None
        ) = None,
    ) -> None:
        self._conversation_store = conversation_store
        self._memory_store = memory_store
        self._memory_extractor = memory_extractor
        self._memory_retriever = memory_retriever
        self._message_id_factory = message_id_factory
        self._clock = clock
        self._audit = audit_sink
        self._write_transaction = write_transaction
        self._interaction_outcome_observer = interaction_outcome_observer
        self._user_initiated_interaction_observer = (
            user_initiated_interaction_observer
        )

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

    def archive(self, message: ConversationMessage) -> None:
        """先单独持久化 L0，供会失败的外部提取器使用。

        规则基线正常写入仍使用 observe 的原子事务。日常模型提取先用本
        方法保住来源；运行期暂停 L1 写入时也复用它，避免形成审计断层。
        """
        if not message.content.strip():
            raise EmptyMessageError("聊天消息不能为空。")
        with self._write_transaction():
            self._conversation_store.save(message)
            if (
                message.role == MessageRole.USER
                and self._interaction_outcome_observer is not None
            ):
                self._interaction_outcome_observer.record_user_message(message)
            if (
                message.role == MessageRole.USER
                and self._user_initiated_interaction_observer is not None
            ):
                self._user_initiated_interaction_observer.record_user_message(message)
        if message.role == MessageRole.USER:
            self._audit("user_saved", turn_id=str(message.id))

    def extract(self, message: ConversationMessage) -> tuple[AtomicMemory, ...]:
        """在数据库写事务外运行可替换提取策略。"""
        if message.role != MessageRole.USER:
            return ()
        return self._memory_extractor.extract(message)

    def report_extraction_failure(self, message: ConversationMessage, *, code: str) -> None:
        """记录脱敏失败代码；不把用户正文或供应商响应写进审计日志。"""
        self._audit("extraction_failed", turn_id=str(message.id), warning_code=code)

    def persist_extracted(
        self,
        message: ConversationMessage,
        candidate_memories: tuple[AtomicMemory, ...],
    ) -> tuple[MemoryWriteOperation, ...]:
        """把已经校验的 L1 候选原子写入，并绑定到已归档 L0。"""
        if self._conversation_store.get(message.id) is None:
            raise ValueError("写入 L1 前必须先归档对应的 L0 消息。")
        with self._write_transaction():
            return self._persist_memories(message, candidate_memories)

    def _observe(self, message: ConversationMessage) -> tuple[MemoryWriteOperation, ...]:
        self._conversation_store.save(message)
        if message.role != MessageRole.USER:
            return ()
        if self._interaction_outcome_observer is not None:
            self._interaction_outcome_observer.record_user_message(message)
        if self._user_initiated_interaction_observer is not None:
            self._user_initiated_interaction_observer.record_user_message(message)
        turn_id = str(message.id)
        self._audit("user_saved", turn_id=turn_id)

        # 从当前 L0 消息提取零条或多条 L1 记忆。
        candidate_memories = self._memory_extractor.extract(message)
        return self._persist_memories(message, candidate_memories)

    def _persist_memories(
        self,
        message: ConversationMessage,
        candidate_memories: tuple[AtomicMemory, ...],
    ) -> tuple[MemoryWriteOperation, ...]:
        """去重并保存候选；调用方负责建立所需的写事务。"""
        turn_id = str(message.id)

        memory_operations = []

        for candidate_memory in candidate_memories:
            candidate_dedup_key = canonicalize_l1_for_exact_dedup(
                candidate_memory.content
            )
            # 同一句临时状态在有效期结束后可以重新成为一条新 L1；不能把
            # 新证据挂到已过期的旧记录上，否则它仍会因为旧 valid_to 而不可召回。
            existing_memory = next((
                memory for memory in self._memory_store.list_active()
                if memory.subject_id == candidate_memory.subject_id
                and canonicalize_l1_for_exact_dedup(memory.content)
                == candidate_dedup_key
                and is_memory_effective(memory, message.created_at)
            ), None)

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
