"""验证 L0、L1 和聊天结果之间的最小数据关系。"""

from datetime import UTC, datetime

from longmemory.application.chat.dto import ChatResult
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.models import AtomicMemory


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

    memory = AtomicMemory(
        id=MemoryId("memory-001"),
        content="用户养了一只叫豆包的猫。",
        source_message_id=message_id,
        created_at=created_at,
    )

    result = ChatResult(
        user_message=user_message,
        saved_memories=(memory,),
        retrieved_memories=(),
        answer="好的，我记住了。",
    )

    assert result.user_message.content == "我养了一只叫豆包的猫。"
    assert result.saved_memories == (memory,)
    assert result.retrieved_memories == ()
    assert result.saved_memories[0].source_message_id == result.user_message.id