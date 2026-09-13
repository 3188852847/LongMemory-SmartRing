"""用可替换文本编码器生成有界 L1 语义关系候选对。"""

from dataclasses import dataclass
from hashlib import sha256
import math
from typing import Sequence

from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_relations import SemanticRelationPair
from longmemory.core.memory.retrieval.vector import TextEncoder, unit_vector


PAIRING_VERSION = "l1-semantic-pairing-v1"
MAX_PAIRING_MEMORIES = 500
MAX_PAIRING_CANDIDATES = 20


@dataclass(frozen=True, slots=True)
class SemanticPairCandidate:
    pair: SemanticRelationPair
    cosine_similarity: float


def _pair_id(left_id: str, right_id: str) -> str:
    return sha256(
        f"{PAIRING_VERSION}\0{left_id}\0{right_id}".encode("utf-8")
    ).hexdigest()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_unit, right_unit = unit_vector(left), unit_vector(right)
    if len(left_unit) != len(right_unit):
        raise ValueError("semantic_pairing_vector_dimension_mismatch")
    return max(-1.0, min(1.0, math.fsum(
        a * b for a, b in zip(left_unit, right_unit, strict=True)
    )))


def propose_semantic_relation_pairs(
    memories: tuple[AtomicMemory, ...],
    *,
    encoder: TextEncoder,
    maximum_candidates: int = MAX_PAIRING_CANDIDATES,
) -> tuple[SemanticPairCandidate, ...]:
    """编码一次当前 L1，只在同一主体内按余弦排序，不解释分数含义。"""

    if (
        type(maximum_candidates) is not int
        or not 1 <= maximum_candidates <= MAX_PAIRING_CANDIDATES
    ):
        raise ValueError("semantic_pairing_candidate_limit_invalid")
    if len(memories) > MAX_PAIRING_MEMORIES:
        raise ValueError("semantic_pairing_memory_limit_exceeded")
    if not memories:
        return ()
    ids = [str(item.id) for item in memories]
    if len(set(ids)) != len(ids):
        raise ValueError("semantic_pairing_memory_id_duplicate")

    vectors = tuple(encoder.encode_documents([item.content for item in memories]))
    if len(vectors) != len(memories):
        raise ValueError("semantic_pairing_vector_count_mismatch")
    normalized = tuple(unit_vector(vector) for vector in vectors)
    ranked: list[SemanticPairCandidate] = []
    for left_index, left in enumerate(memories):
        for right_index in range(left_index + 1, len(memories)):
            right = memories[right_index]
            if left.subject_id != right.subject_id:
                continue
            # ID 顺序固定后，输入排列变化不会产生新的候选身份。
            if str(left.id) <= str(right.id):
                first, second = left, right
                first_vector, second_vector = normalized[left_index], normalized[right_index]
            else:
                first, second = right, left
                first_vector, second_vector = normalized[right_index], normalized[left_index]
            similarity = _cosine(first_vector, second_vector)
            pair = SemanticRelationPair(
                pair_id=_pair_id(str(first.id), str(second.id)),
                left_memory_id=str(first.id),
                right_memory_id=str(second.id),
                left_content=first.content,
                right_content=second.content,
                left_recorded_at=first.recorded_at.isoformat(),
                right_recorded_at=second.recorded_at.isoformat(),
            )
            ranked.append(SemanticPairCandidate(pair, similarity))
    ranked.sort(key=lambda item: (
        -item.cosine_similarity,
        item.pair.left_memory_id,
        item.pair.right_memory_id,
    ))
    return tuple(ranked[:maximum_candidates])
