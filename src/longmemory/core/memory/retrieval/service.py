"""根据当前问题召回并排序相关 L1 记忆。"""

import re

from longmemory.core.memory.l1_atomic.contracts import MemoryStore
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.retrieval.vector import ExactVectorIndex, VectorDocument


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


def keyword_overlap_score(query: str, content: str) -> int:
    """供不同个人记忆层复用的可解释词项重合分；0 表示不应命中。"""

    return len(_extract_terms(query) & _extract_terms(content))


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
            overlap_count = keyword_overlap_score(query, memory.content)

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


class HybridMemoryRetriever:
    """将关键词与本地稠密排名融合的小规模日常检索器。

    稠密分数没有被解释为“答案存在概率”，也不使用未经校准的阈值。
    当前库很小时保留精确扫描；只追加 L1 时增量编码，删除/退役或内容
    变化时重建内存索引。向量和个人文本不另存一份磁盘副本。
    """

    name = "keyword_dense_rrf_v1"

    def __init__(self, memory_store: MemoryStore, encoder) -> None:
        self._memory_store = memory_store
        self._keyword = KeywordMemoryRetriever(memory_store)
        self._encoder = encoder
        self._index = ExactVectorIndex((), (), encoder_id=encoder.identity)
        self._signature: tuple[tuple[str, str], ...] = ()
        self._warning_code: str | None = None

    def _documents(self, memories: tuple[AtomicMemory, ...]) -> tuple[VectorDocument, ...]:
        return tuple(
            VectorDocument(
                str(memory.id),
                memory.content,
                tuple(str(e.source_message_id) for e in self._memory_store.list_evidence(memory.id)),
            )
            for memory in memories
        )

    def _refresh(self, memories: tuple[AtomicMemory, ...]) -> None:
        signature = tuple((str(memory.id), memory.content) for memory in memories)
        if signature == self._signature:
            return
        documents = self._documents(memories)
        # list_active 的稳定顺序允许纯追加时只编码新条目。纠正、删除和
        # 将来的退役会破坏前缀，此时完整重建以避免陈旧条目继续召回。
        if self._signature and signature[:len(self._signature)] == self._signature:
            new_documents = documents[len(self._signature):]
            new_vectors = self._encoder.encode_documents([item.content for item in new_documents])
            self._index = ExactVectorIndex(
                documents,
                (*self._index.vectors, *new_vectors),
                encoder_id=self._encoder.identity,
            )
        else:
            self._index = ExactVectorIndex.build(
                documents, self._encoder, encoder_id=self._encoder.identity,
            )
        self._signature = signature

    def retrieve(self, query: str, *, limit: int = 5) -> tuple[AtomicMemory, ...]:
        self._warning_code = None
        if limit <= 0:
            return ()
        keyword = self._keyword.retrieve(query, limit=max(20, limit * 4))
        memories = self._memory_store.list_active()
        if not memories:
            # 空库没有候选，不能为了“执行过语义模型”而制造一次无意义编码。
            return ()
        by_id = {str(memory.id): memory for memory in memories}
        try:
            self._refresh(memories)
            dense = tuple(
                by_id[document.item_id]
                for document, _score in self._index.search(
                    self._encoder.encode_query(query), limit=max(20, limit * 4),
                )
            )
        except (OSError, RuntimeError, ValueError):
            # 日常入口继续使用可解释基线，但通过 consume_diagnostics 明确
            # 告知调用方发生了降级；不吞掉 SQLite 等存储错误。
            self._warning_code = "dense_retrieval_failed"
            return keyword[:limit]

        # Reciprocal Rank Fusion 只融合次序，不把不同量纲的词项分与
        # 余弦分硬相加。60 是算法平滑常数，不是相似度/置信阈值。
        scores: dict[str, float] = {}
        order: dict[str, int] = {}
        for ranking in (keyword, dense):
            for rank, memory in enumerate(ranking, start=1):
                key = str(memory.id)
                order.setdefault(key, len(order))
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
        ranked = sorted(scores, key=lambda key: (-scores[key], order[key]))
        return tuple(by_id[key] for key in ranked[:limit])

    def consume_diagnostics(self) -> dict[str, str | None]:
        """返回并清除最近一次串行调用状态，避免警告污染下一轮。"""
        warning = self._warning_code
        self._warning_code = None
        return {
            "strategy": "keyword_fallback" if warning else self.name,
            "warning_code": warning,
        }
