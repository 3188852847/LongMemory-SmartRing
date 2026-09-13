from datetime import UTC, datetime

from longmemory.application.memory_management.semantic_relation_preview import (
    SemanticRelationPreviewService,
)
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelation,
    SemanticRelationDecision,
    SemanticRelationReason,
    SemanticRelationReview,
)


class Encoder:
    def __init__(self):
        self.calls = 0

    def encode_documents(self, texts):
        self.calls += 1
        return [[1.0, 0.0], [0.9, 0.1]][:len(texts)]


class Reviewer:
    version = "reviewer-test-v1"

    def __init__(self):
        self.calls = 0

    def review(self, pairs):
        self.calls += 1
        pair = pairs[0]
        return SemanticRelationReview(self.version, (
            SemanticRelationDecision(
                pair.pair_id,
                SemanticRelation.POSSIBLE_CONFLICT,
                SemanticRelationReason.DIFFERENT_VALUE_SAME_ATTRIBUTE,
                "喜欢乌龙茶",
                "喜欢咖啡",
            ),
        ))


def memory(identifier, content):
    return AtomicMemory(
        MemoryId(identifier), MemorySubjectId("user:self"), content,
        datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_preview_skips_encoder_and_model_when_fewer_than_two_memories():
    encoder, reviewer = Encoder(), Reviewer()
    service = SemanticRelationPreviewService(encoder=encoder, reviewer=reviewer)

    result = service.preview(
        (memory("memory-a", "用户喜欢乌龙茶。"),),
        generated_at=datetime(2026, 9, 13, tzinfo=UTC),
    )

    assert result.status == "insufficient_memories"
    assert result.candidates == ()
    assert encoder.calls == reviewer.calls == 0


def test_preview_pairs_then_reviews_once_without_mutating_memories():
    encoder, reviewer = Encoder(), Reviewer()
    service = SemanticRelationPreviewService(encoder=encoder, reviewer=reviewer)
    memories = (
        memory("memory-a", "用户喜欢乌龙茶。"),
        memory("memory-b", "用户喜欢咖啡。"),
    )

    result = service.preview(
        memories, generated_at=datetime(2026, 9, 13, tzinfo=UTC),
    )

    assert result.status == "completed"
    assert result.scanned_memory_count == 2
    assert len(result.candidates) == 1
    candidate, decision = result.candidates[0]
    assert candidate.pair.left_memory_id == "memory-a"
    assert decision.relation is SemanticRelation.POSSIBLE_CONFLICT
    assert encoder.calls == reviewer.calls == 1
    assert tuple(item.content for item in memories) == (
        "用户喜欢乌龙茶。", "用户喜欢咖啡。",
    )
