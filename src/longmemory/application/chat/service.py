"""编排保存、提取、检索、上下文构建和回答。"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4
from time import monotonic


from longmemory.application.chat.contracts import AnswerGenerator
from longmemory.application.chat.dto import ChatResult
from longmemory.application.memory_turn import MemoryTurnService
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


def _new_message_id() -> MessageId:
    """为正式运行生成全局唯一的 L0 消息 ID。"""

    return MessageId(str(uuid4()))


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def _ignore_event(event: str, **fields: object) -> None:
    """默认不绑定任何日志设施；正式装配时注入审计接收函数。"""


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
        audit_sink: Callable[..., None] = _ignore_event,
        memory_turn_service: MemoryTurnService | None = None,
    ) -> None:
        self._conversation_store = conversation_store
        self._answer_generator = answer_generator
        self._message_id_factory = message_id_factory
        self._clock = clock
        self._audit = audit_sink

        # CLI 与小智共用同一记忆用例，避免维护两套提取/去重逻辑。
        self._memory_turn = memory_turn_service if memory_turn_service is not None else MemoryTurnService(
            conversation_store=conversation_store, memory_store=memory_store,
            memory_extractor=memory_extractor, memory_retriever=memory_retriever,
            message_id_factory=message_id_factory, clock=clock, audit_sink=audit_sink,
        )

    def chat(self, text: str) -> ChatResult:
        """先运行记忆用例，再生成并保存助手回答，保留原 CLI 行为。"""
        started = monotonic()
        prepared = self._memory_turn.prepare(text)
        user_message = prepared.user_message
        turn_id = str(user_message.id)
        memory_operations = prepared.memory_operations
        retrieved_memories = prepared.retrieved_memories
        memory_context = prepared.memory_context
        try:
            answer = self._answer_generator.generate(query=text, memory_context=memory_context)
        except Exception:
            self._audit("answer_failed", turn_id=turn_id,
                      duration_ms=round((monotonic() - started) * 1000))
            raise

        # 助手回答同样属于 L0 原始对话。保存角色和原文，
        # 但不把它重新送入记忆提取器，避免生成内容变成用户事实。
        assistant_message = ConversationMessage(
            id=self._message_id_factory(),
            role=MessageRole.ASSISTANT,
            content=answer,
            created_at=self._clock(),
        )
        self._conversation_store.save(assistant_message)
        self._audit("assistant_saved", turn_id=turn_id, assistant_id=str(assistant_message.id),
                  duration_ms=round((monotonic() - started) * 1000))

        return ChatResult(
            user_message=user_message,
            assistant_message=assistant_message,
            memory_operations=tuple(memory_operations),
            retrieved_memories=retrieved_memories,
            answer=answer,
        )
