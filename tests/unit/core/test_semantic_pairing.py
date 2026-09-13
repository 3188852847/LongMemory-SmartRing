from datetime import UTC, datetime

import pytest

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_pairing import (
    propose_semantic_relation_pairs,
)


NOW = datetime(2026, 9, 13, tzinfo=UTC)


def memory(key, content, subject="user:self"):
    return AtomicMemory(MemoryId(key), MemorySubjectId(subject), content, NOW)


class FakeEncoder:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode_documents(self, texts):
        self.calls.append(tuple(texts))
        return self.vectors

    def encode_query(self, text):
        raise AssertionError("配对不应使用查询编码前缀")


def test_ranks_same_subject_pairs_and_keeps_score_as_candidate_signal():
    items = (
        memory("a", "用户以前住在南京。"),
        memory("b", "用户现在住在合肥。"),
        memory("c", "用户喜欢乌龙茶。"),
        memory("d", "另一主体住在南京。", "person:other"),
    )
    encoder = FakeEncoder(((1, 0), (.9, .1), (0, 1), (1, 0)))

    result = propose_semantic_relation_pairs(items, encoder=encoder, maximum_candidates=2)

    assert encoder.calls == [tuple(item.content for item in items)]
    assert [(item.pair.left_memory_id, item.pair.right_memory_id) for item in result] == [
        ("a", "b"), ("b", "c"),
    ]
    assert result[0].cosine_similarity > result[1].cosine_similarity
    assert all("d" not in (item.pair.left_memory_id, item.pair.right_memory_id)
               for item in result)


def test_pair_identity_and_order_are_stable_when_input_order_changes():
    left = memory("a", "用户养了一只猫。")
    right = memory("b", "用户现在养了一只猫。")

    first = propose_semantic_relation_pairs(
        (left, right), encoder=FakeEncoder(((1, 0), (1, 0))),
    )[0]
    second = propose_semantic_relation_pairs(
        (right, left), encoder=FakeEncoder(((1, 0), (1, 0))),
    )[0]

    assert first.pair.pair_id == second.pair.pair_id
    assert first.pair.left_memory_id == second.pair.left_memory_id == "a"
    assert first.pair.right_memory_id == second.pair.right_memory_id == "b"


def test_empty_input_never_calls_encoder():
    result = propose_semantic_relation_pairs((), encoder=FakeEncoder(()))

    assert result == ()


@pytest.mark.parametrize("limit", [0, -1, 21, True])
def test_rejects_invalid_candidate_budget(limit):
    with pytest.raises(ValueError, match="semantic_pairing_candidate_limit_invalid"):
        propose_semantic_relation_pairs((), encoder=FakeEncoder(()), maximum_candidates=limit)


def test_rejects_duplicate_ids_and_wrong_vector_count():
    duplicate = (memory("a", "事实一"), memory("a", "事实二"))
    with pytest.raises(ValueError, match="semantic_pairing_memory_id_duplicate"):
        propose_semantic_relation_pairs(duplicate, encoder=FakeEncoder(((1,), (1,))))

    with pytest.raises(ValueError, match="semantic_pairing_vector_count_mismatch"):
        propose_semantic_relation_pairs(
            (memory("a", "事实一"), memory("b", "事实二")),
            encoder=FakeEncoder(((1,),)),
        )
