import pytest

from longmemory.application.temporal_recall import (
    TemporalQueryIntent,
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
