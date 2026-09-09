"""日常混合召回只验证融合、缓存和显式降级，不冒充真实模型质量。"""

from datetime import UTC, datetime
from types import SimpleNamespace

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.models import AtomicMemory
from longmemory.core.memory.retrieval.service import HybridMemoryRetriever


def memory(key: str, content: str) -> AtomicMemory:
    return AtomicMemory(MemoryId(key), MemorySubjectId("user:self"), content,
                        datetime(2026, 9, 6, tzinfo=UTC))


class Store:
    def __init__(self, memories):
        self.memories = list(memories)

    def list_active(self):
        return tuple(self.memories)

    def list_evidence(self, memory_id):
        return (SimpleNamespace(source_message_id=f"source-{memory_id}"),)


class Encoder:
    identity = "synthetic-encoder"

    def __init__(self):
        self.document_batches = []

    def encode_documents(self, texts):
        self.document_batches.append(list(texts))
        return [self._vector(text) for text in texts]

    def encode_query(self, text):
        return self._vector(text)

    @staticmethod
    def _vector(text):
        if "小林" in text or "名字" in text or "什么" in text:
            return [1.0, 0.0, 0.0]
        if "猫" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def test_dense_recovers_cross_expression_and_reports_strategy():
    store = Store([memory("name", "用户叫小林。"), memory("cat", "用户养猫。")])
    retriever = HybridMemoryRetriever(store, Encoder())
    assert retriever.retrieve("我的名字是什么")[0].id == "name"
    assert retriever.consume_diagnostics() == {
        "strategy": "keyword_dense_rrf_v1", "warning_code": None,
    }


def test_append_is_incremental_but_delete_rebuilds_active_corpus():
    encoder = Encoder()
    store = Store([memory("name", "用户叫小林。"), memory("cat", "用户养猫。")])
    retriever = HybridMemoryRetriever(store, encoder)
    retriever.retrieve("名字")
    assert encoder.document_batches == [["用户叫小林。", "用户养猫。"]]
    store.memories.append(memory("tea", "用户喜欢乌龙茶。"))
    retriever.retrieve("乌龙茶")
    assert encoder.document_batches[-1] == ["用户喜欢乌龙茶。"]
    store.memories.pop(0)
    retriever.retrieve("猫")
    assert encoder.document_batches[-1] == ["用户养猫。", "用户喜欢乌龙茶。"]


def test_dense_failure_explicitly_falls_back_to_keyword_once():
    class Broken(Encoder):
        def encode_query(self, text):
            raise RuntimeError("synthetic encoder failure")

    store = Store([memory("cat", "用户养猫。"), memory("tea", "用户喜欢乌龙茶。")])
    retriever = HybridMemoryRetriever(store, Broken())
    assert tuple(item.id for item in retriever.retrieve("猫")) == ("cat",)
    assert retriever.consume_diagnostics() == {
        "strategy": "keyword_fallback", "warning_code": "dense_retrieval_failed",
    }
    assert retriever.consume_diagnostics()["warning_code"] is None


def test_non_positive_limit_does_not_encode():
    encoder = Encoder()
    retriever = HybridMemoryRetriever(Store([memory("cat", "用户养猫。")]), encoder)
    assert retriever.retrieve("猫", limit=0) == ()
    assert encoder.document_batches == []


def test_empty_memory_corpus_does_not_encode_query():
    encoder = Encoder()
    retriever = HybridMemoryRetriever(Store([]), encoder)
    assert retriever.retrieve("我的名字是什么") == ()
    assert encoder.document_batches == []


def test_expired_memory_is_removed_from_dense_corpus():
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    expired = AtomicMemory(
        MemoryId("mood"), MemorySubjectId("user:self"), "用户今天心情不好。",
        datetime(2026, 9, 6, tzinfo=UTC), valid_to=now,
    )
    encoder = Encoder()
    retriever = HybridMemoryRetriever(
        Store([expired, memory("cat", "用户养猫。")]), encoder,
        clock=lambda: now,
    )

    assert "mood" not in tuple(item.id for item in retriever.retrieve("心情"))
    assert encoder.document_batches == [["用户养猫。"]]
