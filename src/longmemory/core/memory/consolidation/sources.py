"""低频 L1→L2 整理的来源批次；正文只在执行期内存中存在。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId, ScenarioId

from .models import ConsolidationCursor


@dataclass(frozen=True, slots=True)
class L1ConsolidationSource:
    memory_id: MemoryId
    subject_id: MemorySubjectId
    content: str
    recorded_at: datetime
    source_message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.content.strip() or not self.source_message_ids:
            raise ValueError("consolidation_l1_source_invalid")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at_timezone_required")
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("consolidation_l1_source_messages_invalid")


@dataclass(frozen=True, slots=True)
class L1ConsolidationBatch:
    """新来源按游标顺序推进；旧未归组来源仅作本轮补充上下文。"""

    sources: tuple[L1ConsolidationSource, ...]
    pending_new_source_count: int
    selected_new_source_count: int
    next_cursor: ConsolidationCursor | None

    def __post_init__(self) -> None:
        if (
            self.pending_new_source_count < 0
            or self.selected_new_source_count < 0
            or self.selected_new_source_count > len(self.sources)
            or self.selected_new_source_count > self.pending_new_source_count
        ):
            raise ValueError("consolidation_l1_batch_count_invalid")
        if (self.selected_new_source_count > 0) != (self.next_cursor is not None):
            raise ValueError("consolidation_l1_batch_cursor_invalid")
        keys = {source.memory_id for source in self.sources}
        if len(keys) != len(self.sources):
            raise ValueError("consolidation_l1_batch_duplicate_source")


@dataclass(frozen=True, slots=True)
class L2ConsolidationEvidence:
    message_id: str
    content: str
    observation_day: str

    def __post_init__(self) -> None:
        if not self.message_id.strip() or not self.content.strip() or not self.observation_day.strip():
            raise ValueError("consolidation_l2_evidence_invalid")


@dataclass(frozen=True, slots=True)
class L2ConsolidationSource:
    scenario_id: ScenarioId
    subject_id: MemorySubjectId
    content: str
    generated_at: datetime
    evidence: tuple[L2ConsolidationEvidence, ...]

    def __post_init__(self) -> None:
        if not self.content.strip() or not self.evidence:
            raise ValueError("consolidation_l2_source_invalid")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at_timezone_required")

    @property
    def source_message_ids(self) -> tuple[str, ...]:
        return tuple(item.message_id for item in self.evidence)

    @property
    def observation_days(self) -> tuple[str, ...]:
        return tuple(sorted({item.observation_day for item in self.evidence}))


@dataclass(frozen=True, slots=True)
class L2ConsolidationBatch:
    sources: tuple[L2ConsolidationSource, ...]
    pending_new_source_count: int
    selected_new_source_count: int
    next_cursor: ConsolidationCursor | None

    def __post_init__(self) -> None:
        if (
            self.pending_new_source_count < 0
            or self.selected_new_source_count < 0
            or self.selected_new_source_count > len(self.sources)
            or self.selected_new_source_count > self.pending_new_source_count
        ):
            raise ValueError("consolidation_l2_batch_count_invalid")
        if (self.selected_new_source_count > 0) != (self.next_cursor is not None):
            raise ValueError("consolidation_l2_batch_cursor_invalid")
        if len({source.scenario_id for source in self.sources}) != len(self.sources):
            raise ValueError("consolidation_l2_batch_duplicate_source")
