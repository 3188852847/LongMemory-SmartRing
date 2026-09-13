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
