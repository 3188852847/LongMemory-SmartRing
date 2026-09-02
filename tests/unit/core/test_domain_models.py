"""验证 L0、L1 和聊天结果之间的最小数据关系。"""

from datetime import UTC, datetime

import pytest

from longmemory.application.chat.dto import ChatResult
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.models import (
    CURRENT_USER_SUBJECT_ID,
    AtomicMemory,
    MemoryEvidence,
    MemoryOperationType,
    MemorySourceType,
    MemoryWriteOperation,
)


def test_chat_result_preserves_memory_source_relationship() -> None:
    """聊天结果中的记忆能够追溯到对应的原始用户消息。"""

    created_at = datetime.now(UTC)
    message_id = MessageId("message-001")

    user_message = ConversationMessage(
        id=message_id,
        role=MessageRole.USER,
        content="我养了一只叫豆包的猫。",
        created_at=created_at,
    )
    assistant_message = ConversationMessage(
        id=MessageId("message-002"),
        role=MessageRole.ASSISTANT,
        content="好的，我记住了。",
        created_at=created_at,
    )

    memory = AtomicMemory(
        id=MemoryId("memory-001"),
        subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户养了一只叫豆包的猫。",
        recorded_at=created_at,
    )
    evidence = MemoryEvidence(
        memory_id=memory.id,
        source_message_id=message_id,
        source_type=MemorySourceType.USER_STATED,
        linked_at=created_at,
    )

    result = ChatResult(
        user_message=user_message,
        assistant_message=assistant_message,
        memory_operations=(
            MemoryWriteOperation(
                operation=MemoryOperationType.ADD,
                memory=memory,
                evidence=evidence,
            ),
        ),
        retrieved_memories=(),
        answer="好的，我记住了。",
    )

    assert result.user_message.content == "我养了一只叫豆包的猫。"
    assert result.assistant_message.role == MessageRole.ASSISTANT
    assert result.saved_memories == (memory,)
    assert result.retrieved_memories == ()
    assert result.memory_operations[0].evidence.source_message_id == (
        result.user_message.id
    )


def test_supersede_operation_requires_old_memory_id() -> None:
    """预留的取代操作不能丢失被取代记忆的身份。"""

    recorded_at = datetime.now(UTC)
    memory = AtomicMemory(
        id=MemoryId("memory-new"),
        subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户现在住在上海。",
        recorded_at=recorded_at,
    )
    evidence = MemoryEvidence(
        memory_id=memory.id,
        source_message_id=MessageId("message-new"),
        source_type=MemorySourceType.USER_STATED,
        linked_at=recorded_at,
    )

    with pytest.raises(ValueError, match="superseded_memory_id"):
        MemoryWriteOperation(
            operation=MemoryOperationType.SUPERSEDE,
            memory=memory,
            evidence=evidence,
        )
