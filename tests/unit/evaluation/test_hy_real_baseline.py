from datetime import UTC,datetime
from dataclasses import replace
import json

import pytest

from longmemory.evaluation.comparison.hy_real_baseline import DailyBGEReplay
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.contracts import MemoryEvent


def test_daily_algorithm_replay_maps_original_sources_without_writing_questions(tmp_path):
    class Producer:
        def propose(self,*,source_text):
            return json.dumps({"schema_version":1,"operation":"ADD","facts":[{"content":source_text,"quote":source_text}]},ensure_ascii=False)
    class Encoder:
        identity="synthetic-vector"
        def encode_documents(self,texts):return [[1.,0.] for text in texts]
        def encode_query(self,text):return [1.,0.]
    def open_(create):return DailyBGEReplay(tmp_path,create=create,settings=ModelSettings(),encoder=Encoder(),producer=Producer())
    event=MemoryEvent("original-1","user","用户喜欢无糖乌龙茶",datetime(2026,1,1,tzinfo=UTC),"s1")
    method=open_(True)
    try:
        assert method.observe(event).event_id==event.event_id
        method.observe(replace(event,event_id="assistant-1",role="assistant",content="建议喝拿铁"))
        with pytest.raises(ValueError,match="replayed_event"):method.observe(event)
    finally:method.close()
    reopened=open_(False)
    try:
        support=reopened.recall("喜欢喝什么茶")
        assert event.event_id in {source for item in support.retrieved for source in item.source_event_ids}
        assert len(reopened.mapping)==2
        assert all("拿铁" not in item.content for item in support.retrieved)
    finally:reopened.close()
