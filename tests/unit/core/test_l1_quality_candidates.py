"""L1 质量候选只负责发现，不替用户修改事实。"""

from datetime import UTC, datetime

from longmemory.core.common.identifiers import MemoryId
from longmemory.core.memory.l1_atomic.models import (
    AtomicMemory,
    CURRENT_USER_SUBJECT_ID,
)
from longmemory.core.memory.quality.l1_candidates import find_l1_quality_candidates


NOW = datetime(2026, 9, 13, tzinfo=UTC)


def memory(key: str, content: str) -> AtomicMemory:
    return AtomicMemory(MemoryId(key), CURRENT_USER_SUBJECT_ID, content, NOW)


def test_finds_normalized_duplicate_without_treating_score_as_confidence():
    items = find_l1_quality_candidates((
        memory("a", "用户喜欢乌龙茶。"),
        memory("b", " 此人喜欢乌龙茶 "),
    ))

    assert len(items) == 1
    assert items[0].kind == "normalized_duplicate"
    assert items[0].similarity == 1.0


def test_finds_only_explicit_opposing_phrases_as_possible_conflict():
    items = find_l1_quality_candidates((
        memory("a", "用户喜欢喝咖啡。"),
        memory("b", "用户不喜欢喝咖啡。"),
        memory("c", "用户最近常去咖啡馆。"),
    ))

    conflicts = [item for item in items if item.kind == "possible_conflict"]
    assert [(str(item.left.id), str(item.right.id)) for item in conflicts] == [("a", "b")]
    assert "喜欢/不喜欢" in conflicts[0].reason


def test_reports_high_lexical_overlap_but_ignores_unrelated_facts():
    items = find_l1_quality_candidates((
        memory("a", "用户最近喜欢喝茉莉花茶。"),
        memory("b", "用户喜欢喝茉莉花茶。"),
        memory("c", "用户计划周五完成毕业设计汇报。"),
    ))

    assert [(item.kind, str(item.left.id), str(item.right.id)) for item in items] == [
        ("lexical_near_duplicate", "a", "b"),
    ]


def test_candidate_limit_is_deterministic():
    memories = tuple(memory(str(index), "用户喜欢乌龙茶。") for index in range(4))
    first = find_l1_quality_candidates(memories, maximum_candidates=2)
    second = find_l1_quality_candidates(memories, maximum_candidates=2)

    assert first == second
    assert len(first) == 2
