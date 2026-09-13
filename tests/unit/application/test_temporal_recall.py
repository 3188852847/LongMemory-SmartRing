from datetime import UTC, datetime

import pytest

from longmemory.application.temporal_recall import (
    TemporalQueryIntent,
    analyze_temporal_query,
    classify_temporal_query,
)


def test_classifies_only_explicit_historical_queries():
    assert classify_temporal_query("我以前住在哪里？") is TemporalQueryIntent.HISTORY
    assert classify_temporal_query("我搬到合肥之前住哪里") is TemporalQueryIntent.HISTORY
    assert classify_temporal_query("我是什么时候搬到合肥的？") is TemporalQueryIntent.CHANGE_TIME
    assert classify_temporal_query("我何时开始喜欢乌龙茶") is TemporalQueryIntent.CHANGE_TIME


def test_current_or_vague_time_queries_do_not_unlock_history():
    assert classify_temporal_query("我现在住在哪里？") is None
    assert classify_temporal_query("我的猫叫什么？") is None
    assert classify_temporal_query("什么时候吃饭？") is None
    assert classify_temporal_query("后来者居上是什么意思？") is None
    assert classify_temporal_query("原来如此") is None


@pytest.mark.parametrize("query", [
    "我以前住在南京。", "我曾经喜欢咖啡", "我知道以前住在哪里",
    "原来如此！", "原来是这样？", "我以前住在南京。今天吃什么？",
    "我过去喜欢咖啡，你呢？", "我曾经住在南京\n现在住哪里？",
])
def test_historical_statements_do_not_unlock_unrelated_questions(query):
    assert classify_temporal_query(query) is None


@pytest.mark.parametrize("query", [
    "我哪天搬到合肥的", "我以前住在哪里，你还记得吗？",
    "请问，我以前住在哪里？", "我以前喜欢咖啡吗",
])
def test_unpunctuated_or_polite_historical_questions_remain_supported(query):
    assert classify_temporal_query(query) is not None


@pytest.mark.parametrize(("query", "label", "start", "end"), [
    ("2025年我住在哪里？", "2025年", "2024-12-31T16:00:00+00:00",
     "2025-12-31T16:00:00+00:00"),
    ("2026年四月我住在哪里", "2026年4月", "2026-03-31T16:00:00+00:00",
     "2026-04-30T16:00:00+00:00"),
    ("2026年5月1日我住哪里？", "2026年5月1日", "2026-04-30T16:00:00+00:00",
     "2026-05-01T16:00:00+00:00"),
    ("2026-05-01时我住哪里", "2026年5月1日", "2026-04-30T16:00:00+00:00",
     "2026-05-01T16:00:00+00:00"),
    ("去年五月我住在哪里？", "2025年5月", "2025-04-30T16:00:00+00:00",
     "2025-05-31T16:00:00+00:00"),
])
def test_extracts_one_explicit_local_date_interval(query, label, start, end):
    result = analyze_temporal_query(
        query, now=datetime(2026, 9, 13, tzinfo=UTC),
    )
    assert result is not None
    assert result.intent is TemporalQueryIntent.DATE
    assert result.date_target is not None
    assert result.date_target.label == label
    assert result.date_target.start.astimezone(UTC).isoformat() == start
    assert result.date_target.end.astimezone(UTC).isoformat() == end


@pytest.mark.parametrize("query", [
    "2026年13月我住哪里？", "2026年2月30日我住哪里？",
    "2025年到2026年我住哪里？", "五月我住在哪里？",
    "2026年5月1我住哪里？", "去年和2025年我住哪里？",
    "2026年13月以前我住哪里？",
    "我2025年住在南京。今天吃什么？",
])
def test_ambiguous_invalid_or_cross_clause_dates_do_not_unlock_history(query):
    assert analyze_temporal_query(
        query, now=datetime(2026, 9, 13, tzinfo=UTC),
    ) is None


def test_temporal_analysis_rejects_naive_clock():
    with pytest.raises(ValueError, match="temporal_query_clock_must_be_aware"):
        analyze_temporal_query(
            "去年我住在哪里？", now=datetime(2026, 9, 13),
        )
