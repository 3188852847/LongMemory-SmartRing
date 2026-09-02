"""验证基础记忆提取策略和来源追踪。"""

from datetime import UTC, datetime

import pytest

from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.extraction.service import (
    MemoryExtractionService,
)
from longmemory.core.memory.models import AtomicMemory


FIXED_TIME = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def make_message(
    content: str,
    role: MessageRole = MessageRole.USER,
) -> ConversationMessage:
    """创建用于提取测试的固定 L0 消息。"""

    return ConversationMessage(
        id=MessageId("message-001"),
        role=role,
        content=content,
        created_at=FIXED_TIME,
    )


def make_extraction_service() -> MemoryExtractionService:
    """创建 ID 和时间均固定的提取服务。"""

    return MemoryExtractionService(
        id_factory=lambda: MemoryId("memory-001"),
        clock=lambda: FIXED_TIME,
    )


def test_extracts_first_person_statement_as_atomic_memory() -> None:
    """第一人称陈述应被规范化并保留 L0 来源。"""

    service = make_extraction_service()
    message = make_message("我养了一只叫豆包的猫。")

    memories = service.extract(message)

    assert memories == (
        AtomicMemory(
            id=MemoryId("memory-001"),
            content="用户养了一只叫豆包的猫。",
            source_message_id=message.id,
            created_at=FIXED_TIME,
        ),
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "我。",
        "我的猫叫什么？",
        "今天天气很好。",
    ],
)
def test_ignores_input_that_baseline_does_not_consider_memory(
    content: str,
) -> None:
    """空文本、问题和非第一人称陈述不应生成记忆。"""

    service = make_extraction_service()

    assert service.extract(make_message(content)) == ()


def test_does_not_extract_user_memory_from_assistant_message() -> None:
    """助手的第一人称陈述不能被误认为用户事实。"""

    service = make_extraction_service()
    assistant_message = make_message(
        "我养了一只叫豆包的猫。",
        role=MessageRole.ASSISTANT,
    )

    assert service.extract(assistant_message) == ()