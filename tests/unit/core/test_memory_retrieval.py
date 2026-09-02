"""验证基础关键词检索和记忆上下文构建。"""

from datetime import UTC, datetime

import pytest

from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.memory.models import AtomicMemory
from longmemory.core.memory.retrieval.context_builder import (
    build_memory_context,
)
from longmemory.core.memory.retrieval.service import KeywordMemoryRetriever


FIXED_TIME = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)


def make_memory(
    memory_id: str,
    content: str,
) -> AtomicMemory:
    """创建用于检索测试的固定记忆。"""

    return AtomicMemory(
        id=MemoryId(memory_id),
        content=content,
        source_message_id=MessageId(f"source-{memory_id}"),
        created_at=FIXED_TIME,
    )


class FakeMemoryStore:
    """只在单元测试中使用的内存存储替身。"""

    def __init__(
        self,
        memories: tuple[AtomicMemory, ...],
    ) -> None:
        self._memories = list(memories)

    def save(self, memory: AtomicMemory) -> None:
        self._memories.append(memory)

    def get(self, memory_id: MemoryId) -> AtomicMemory | None:
        return next(
            (
                memory
                for memory in self._memories
                if memory.id == memory_id
            ),
            None,
        )

    def list_all(self) -> tuple[AtomicMemory, ...]:
        return tuple(self._memories)

    def delete(self, memory_id: MemoryId) -> bool:
        original_count = len(self._memories)

        self._memories = [
            memory
            for memory in self._memories
            if memory.id != memory_id
        ]

        return len(self._memories) < original_count


def test_retrieves_memory_related_to_cat_question() -> None:
    """关于猫的问题只应召回与猫相关的记忆。"""

    cat_memory = make_memory(
        "memory-cat",
        "用户养了一只叫豆包的猫。",
    )
    city_memory = make_memory(
        "memory-city",
        "用户住在杭州。",
    )

    store = FakeMemoryStore((cat_memory, city_memory))
    retriever = KeywordMemoryRetriever(store)

    result = retriever.retrieve("我的猫叫什么？")

    assert result == (cat_memory,)


def test_ranks_more_overlapping_memory_first_and_applies_limit() -> None:
    """重合词项更多的记忆应排在前面，并遵守数量限制。"""

    coffee_memory = make_memory(
        "memory-coffee",
        "用户喜欢喝咖啡。",
    )
    general_preference = make_memory(
        "memory-preference",
        "用户喜欢安静的环境。",
    )

    store = FakeMemoryStore(
        (general_preference, coffee_memory)
    )
    retriever = KeywordMemoryRetriever(store)

    result = retriever.retrieve(
        "我喜欢咖啡。",
        limit=1,
    )

    assert result == (coffee_memory,)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "火星天气怎么样？",
    ],
)
def test_returns_no_memory_for_empty_or_unrelated_query(
    query: str,
) -> None:
    """空查询或无重合查询不应返回伪相关记忆。"""

    cat_memory = make_memory(
        "memory-cat",
        "用户养了一只叫豆包的猫。",
    )

    store = FakeMemoryStore((cat_memory,))
    retriever = KeywordMemoryRetriever(store)

    assert retriever.retrieve(query) == ()


def test_builds_inspectable_context_from_retrieved_memories() -> None:
    """检索结果应被构造成稳定、可检查的上下文文本。"""

    cat_memory = make_memory(
        "memory-cat",
        "用户养了一只叫豆包的猫。",
    )

    context = build_memory_context((cat_memory,))

    assert context == (
        "以下是与当前问题相关的长期记忆：\n"
        "- 用户养了一只叫豆包的猫。"
    )


def test_builds_empty_context_when_nothing_was_retrieved() -> None:
    """没有检索结果时不应生成伪上下文。"""

    assert build_memory_context(()) == ""