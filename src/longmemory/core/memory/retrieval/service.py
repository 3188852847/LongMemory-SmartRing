"""根据当前问题召回并排序相关 L1 记忆。"""

import re

from longmemory.core.memory.contracts import MemoryStore
from longmemory.core.memory.models import AtomicMemory


# 英文和数字按连续单词处理；中文暂时按单字处理。
# 这是 V0.1 的可解释基线，不是成熟的中文分词算法。
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")

# 过滤常见但区分能力较低的中文字符。
# 例如“我的猫叫什么”过滤后仍会留下“猫”等有效词项。
_STOP_TERMS = frozenset(
    "我的你他她它用户是了的一只叫什么吗呢啊呀在有和与"
)


def _extract_terms(text: str) -> frozenset[str]:
    """把文本转换成用于基础匹配的去重词项集合。"""

    tokens = _TOKEN_PATTERN.findall(text.lower())

    return frozenset(
        token
        for token in tokens
        if token not in _STOP_TERMS
    )


class KeywordMemoryRetriever:
    """使用词项重合数量进行排序的基础检索器。

    该实现会扫描全部记忆，适合 V0.1 的少量单用户数据。
    数据规模扩大后，应重新评估全文索引或向量检索。
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory_store = memory_store

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> tuple[AtomicMemory, ...]:
        """返回与查询存在有效词项重合的记忆。"""

        if limit <= 0:
            return ()

        query_terms = _extract_terms(query)

        if not query_terms:
            return ()

        scored_memories: list[tuple[int, AtomicMemory]] = []

        # 已被未来冲突更新流程退役的历史记忆仍可供审计，
        # 但不能继续参与当前回答。
        for memory in self._memory_store.list_active():
            memory_terms = _extract_terms(memory.content)
            overlap_count = len(query_terms & memory_terms)

            # 没有任何有效词项重合时，不返回该记忆。
            if overlap_count == 0:
                continue

            scored_memories.append((overlap_count, memory))

        # Python 排序是稳定的。分数相同时保留 MemoryStore
        # 提供的原始稳定顺序。
        scored_memories.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return tuple(
            memory
            for _, memory in scored_memories[:limit]
        )
