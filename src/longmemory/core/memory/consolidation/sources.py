"""低频 L1→L2 整理的来源批次；正文只在执行期内存中存在。"""

from dataclasses import dataclass
from datetime import datetime

from longmemory.core.common.identifiers import MemoryId, MemorySubjectId

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

