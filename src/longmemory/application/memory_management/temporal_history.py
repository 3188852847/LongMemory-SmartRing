"""从明确的双时间取代边界重建一条 L1 事实变化时间线。"""

from dataclasses import dataclass

from longmemory.core.common.identifiers import MemoryId
from longmemory.core.memory.l1_atomic.models import AtomicMemory


class TemporalHistoryError(ValueError):
    """历史链损坏或存在歧义时使用稳定错误，不猜测事实顺序。"""


@dataclass(frozen=True, slots=True)
class TemporalFactHistory:
    selected_memory_id: MemoryId
    entries: tuple[AtomicMemory, ...]

    @property
    def has_explicit_change(self) -> bool:
        return len(self.entries) > 1


def _is_explicit_change(old: AtomicMemory, new: AtomicMemory) -> bool:
    """只有同主体、首尾时间精确衔接的取代才表示现实事实变化。"""

    return (
        old.subject_id == new.subject_id
        and old.superseded_by_id == new.id
        and old.valid_to is not None
        and new.valid_from is not None
        and old.valid_to == new.valid_from
    )


def build_temporal_fact_history(
    memories: tuple[AtomicMemory, ...], selected_memory_id: MemoryId,
) -> TemporalFactHistory:
    """沿显式变化边界双向遍历；纠错和重复合并不会进入时间线。"""

    by_id = {memory.id: memory for memory in memories}
    if len(by_id) != len(memories):
        raise TemporalHistoryError("temporal_history_duplicate_memory_id")
    selected = by_id.get(selected_memory_id)
    if selected is None:
        raise LookupError("memory_not_found")

    predecessors: dict[MemoryId, list[AtomicMemory]] = {}
    for memory in memories:
        if memory.superseded_by_id is None:
            continue
        target = by_id.get(memory.superseded_by_id)
        if target is not None and _is_explicit_change(memory, target):
            predecessors.setdefault(target.id, []).append(memory)

    first = selected
    visited = {first.id}
    while True:
        previous = predecessors.get(first.id, [])
        if len(previous) > 1:
            raise TemporalHistoryError("temporal_history_ambiguous_predecessor")
        if not previous:
            break
        first = previous[0]
        if first.id in visited:
            raise TemporalHistoryError("temporal_history_cycle")
        visited.add(first.id)

    entries = []
    current = first
    visited = set()
    while True:
        if current.id in visited:
            raise TemporalHistoryError("temporal_history_cycle")
        visited.add(current.id)
        entries.append(current)
        if current.superseded_by_id is None:
            break
        following = by_id.get(current.superseded_by_id)
        if following is None or not _is_explicit_change(current, following):
            break
        current = following
    return TemporalFactHistory(selected_memory_id, tuple(entries))
