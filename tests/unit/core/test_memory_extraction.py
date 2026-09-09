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
from longmemory.core.memory.models import (
    CURRENT_USER_SUBJECT_ID,
    AtomicMemory,
)


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
            subject_id=CURRENT_USER_SUBJECT_ID,
            content="用户养了一只叫豆包的猫。",
            recorded_at=FIXED_TIME,
        ),
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "我。",
        "我的猫叫什么？",
        "我的猫叫什么",
        "我的猫是什么颜色",
        "  我的猫叫什么。  ",
        "我的猫叫什么呢",
        "我的猫呢",
        "我喜欢什么",
        "我是不是养了猫",
        "我有没有养猫",
        "我养猫吗",
        "我的生日在几月",
        "我的猫在哪里",
        "我想知道我的猫叫什么",
        "我养了一只猫。我的猫叫什么",
        "我不知道猫叫什么，能告诉我吗",
        "我的猫叫什么？我忘了",
        "今天天气很好。",
    ],
)
def test_ignores_input_that_baseline_does_not_consider_memory(
    content: str,
) -> None:
    """空文本、问题和非第一人称陈述不应生成记忆。"""

    service = make_extraction_service()

    assert service.extract(make_message(content)) == ()


@pytest.mark.parametrize("content", [
    "我养了一只叫豆包的猫",
    "我的猫是白色的",
    "我不知道猫是什么品种",
    "我记得我的猫叫什么",
    "我什么都喜欢",
    "我哪里都不想去",
])
def test_declarative_sentences_are_not_rejected_for_question_words(content):
    memories = make_extraction_service().extract(make_message(content))
    assert len(memories) == 1
    assert memories[0].content == f"用户{content[1:]}。"


def test_does_not_extract_user_memory_from_assistant_message() -> None:
    """助手的第一人称陈述不能被误认为用户事实。"""

    service = make_extraction_service()
    assistant_message = make_message(
        "我养了一只叫豆包的猫。",
        role=MessageRole.ASSISTANT,
    )

    assert service.extract(assistant_message) == ()


def test_explicit_today_state_gets_a_local_day_validity_window() -> None:
    memory = make_extraction_service().extract(make_message("我今天心情不好"))[0]

    assert memory.content == "用户今天心情不好。"
    assert memory.valid_from == datetime(2026, 9, 2, 16, 0, tzinfo=UTC)
    assert memory.valid_to == datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


def test_explicit_today_interaction_mode_gets_the_same_validity_window() -> None:
    memory = make_extraction_service().extract(
        make_message("我今天只想让你听我说")
    )[0]

    assert memory.valid_from == datetime(2026, 9, 2, 16, 0, tzinfo=UTC)
    assert memory.valid_to == datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "content",
    [
        "我今天决定以后每天跑步",
        "我今天提交毕业设计",
        "我一直很容易焦虑",
    ],
)
def test_non_temporary_statements_do_not_get_invented_expiry(content) -> None:
    memory = make_extraction_service().extract(make_message(content))[0]
    assert memory.valid_from is None
    assert memory.valid_to is None
