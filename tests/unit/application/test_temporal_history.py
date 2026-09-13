from datetime import UTC, datetime

import pytest

from longmemory.application.memory_management.temporal_history import (
    TemporalHistoryError,
    build_temporal_fact_history,
)
from longmemory.core.common.identifiers import MemoryId, MemorySubjectId
from longmemory.core.memory.l1_atomic.models import AtomicMemory


T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 5, 1, tzinfo=UTC)
T2 = datetime(2026, 9, 1, tzinfo=UTC)


def memory(identifier, content, *, valid_from=None, valid_to=None, superseded_by=None):
    return AtomicMemory(
        MemoryId(identifier), MemorySubjectId("user:self"), content, T0,
        valid_from=valid_from, valid_to=valid_to,
        superseded_by_id=MemoryId(superseded_by) if superseded_by else None,
    )


def test_builds_explicit_fact_change_chain_from_any_selected_entry():
    memories = (
        memory("nanjing", "用户住在南京。", valid_to=T1, superseded_by="hefei"),
        memory("hefei", "用户住在合肥。", valid_from=T1, valid_to=T2, superseded_by="shanghai"),
        memory("shanghai", "用户住在上海。", valid_from=T2),
    )

    result = build_temporal_fact_history(memories, MemoryId("hefei"))

    assert [str(item.id) for item in result.entries] == ["nanjing", "hefei", "shanghai"]
    assert result.has_explicit_change is True


def test_does_not_treat_correction_or_duplicate_merge_as_fact_change():
    corrected = memory("corrected", "用户喜欢乌龙茶。")
    old = memory("wrong", "用户喜欢咖啡。", superseded_by="corrected")

    result = build_temporal_fact_history((old, corrected), MemoryId("wrong"))

    assert result.entries == (old,)
    assert result.has_explicit_change is False


def test_rejects_two_explicit_predecessors_instead_of_guessing():
    current = memory("current", "用户住在合肥。", valid_from=T1)
    memories = (
        memory("old-a", "用户住在南京。", valid_to=T1, superseded_by="current"),
        memory("old-b", "用户住在杭州。", valid_to=T1, superseded_by="current"),
        current,
    )

    with pytest.raises(TemporalHistoryError, match="ambiguous_predecessor"):
        build_temporal_fact_history(memories, MemoryId("current"))
