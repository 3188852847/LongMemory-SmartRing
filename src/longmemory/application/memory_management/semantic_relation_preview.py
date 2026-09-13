"""把语义配对与模型复核组合成一次只读、非持久化的开发预览。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.memory.l1_atomic.models import AtomicMemory
from longmemory.core.memory.quality.semantic_pairing import (
    MAX_PAIRING_CANDIDATES,
    MAX_PAIRING_MEMORIES,
    PAIRING_VERSION,
    SemanticPairCandidate,
    propose_semantic_relation_pairs,
)
from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelationDecision,
    SemanticRelationReviewer,
)
from longmemory.core.memory.retrieval.vector import TextEncoder


@dataclass(frozen=True, slots=True)
class SemanticRelationPreview:
    """一次临时预览的完整结果；对象本身不提供任何写入动作。"""

    status: str
    scanned_memory_count: int
    memory_scan_limited: bool
    candidates: tuple[tuple[SemanticPairCandidate, SemanticRelationDecision], ...]
    generated_at: datetime
    pairing_version: str
    reviewer_version: str


class SemanticRelationPreviewService:
    """显式调用时才编码与复核，空库或单条记忆不会调用模型。"""

    def __init__(self, *, encoder: TextEncoder, reviewer: SemanticRelationReviewer):
        self._encoder = encoder
        self._reviewer = reviewer

    @property
    def reviewer_version(self) -> str:
        return self._reviewer.version

    def preview(
        self,
        memories: tuple[AtomicMemory, ...],
        *,
        generated_at: datetime,
    ) -> SemanticRelationPreview:
        scanned = memories[:MAX_PAIRING_MEMORIES]
        if len(scanned) < 2:
            return SemanticRelationPreview(
                "insufficient_memories", len(scanned), len(memories) > len(scanned), (),
                generated_at, PAIRING_VERSION, self._reviewer.version,
            )
        pairs = propose_semantic_relation_pairs(
            scanned,
            encoder=self._encoder,
            maximum_candidates=MAX_PAIRING_CANDIDATES,
        )
        if not pairs:
            return SemanticRelationPreview(
                "no_same_subject_pairs", len(scanned), len(memories) > len(scanned), (),
                generated_at, PAIRING_VERSION, self._reviewer.version,
            )
        review = self._reviewer.review(tuple(item.pair for item in pairs))
        decisions = {item.pair_id: item for item in review.decisions}
        return SemanticRelationPreview(
            "completed", len(scanned), len(memories) > len(scanned),
            tuple((item, decisions[item.pair.pair_id]) for item in pairs),
            generated_at, PAIRING_VERSION, review.reviewer_version,
        )
