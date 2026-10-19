"""旧日用模型提取+BGE/自然命令路径的合成回放；不触日用库。"""

from dataclasses import asdict, replace
from datetime import UTC, datetime
import json

from longmemory.adapters.llm.candidate_extractor import OpenAICompatibleCandidateProducer
from longmemory.adapters.storage.sqlite_temporal_recall import SQLiteTemporalRecallProvider
from longmemory.bootstrap import build_legacy_runtime
from longmemory.core.memory.retrieval.service import HybridMemoryRetriever
from longmemory.methods.contracts import MemorySupport, ObservationResult, RetrievedTrace
from longmemory.methods.daily_llm.method import DailyLLMMemory


class DailyBGEReplay:
    name="longmemory_daily_llm_bge"
    def __init__(self,directory,*,create,settings,encoder,producer=None):
        self.directory=directory
        self.path=directory/"memory.db"
        self.ledger=directory/"replay.json"
        self.create=create
        self.clock=datetime.now(UTC)
        self.mapping={} if create else json.loads(self.ledger.read_text(encoding="utf-8"))
        self.inverse={value:key for key,value in self.mapping.items()}
        self.method=DailyLLMMemory(self.path,producer=producer or OpenAICompatibleCandidateProducer(settings),
            existing_only=not create,retriever_factory=lambda store:HybridMemoryRetriever(store,encoder))
        self.runtime=build_legacy_runtime(self.path,method=self.method,include_personas=False,clock=lambda:self.clock)
        self.temporal=SQLiteTemporalRecallProvider(self.path)
        self.closed=False

    def observe(self,event):
        if not self.create:raise ValueError("baseline_replay_read_only")
        if event.event_id in self.mapping:raise ValueError("baseline_replayed_event_rejected")
        self.clock=event.occurred_at
        # 日用 Runtime 保留自然纠错/事实变化的真实路径；新生成 UUID 在实验账本
        # 显式映射回数据集 event_id，不谎称旧表已有 session_id。
        if event.role=="user":
            result=self.runtime.prepare_user(event.content).observation
        else:
            result=self.runtime.record_assistant(event.content)
        self.mapping[event.event_id]=result.event_id
        self.inverse[result.event_id]=event.event_id
        self.ledger.write_text(json.dumps(self.mapping,sort_keys=True),encoding="utf-8")
        writes=None if result.writes is None else tuple(replace(trace,
            source_event_ids=tuple(self.inverse.get(source,source) for source in trace.source_event_ids)) for trace in result.writes)
        return replace(result,event_id=event.event_id,writes=writes)

    def wait_until_ready(self):self.method.wait_until_ready()

    def recall(self,query):
        # 与 Runtime 的只读召回/日期限制片段相同；不调用 prepare_user 写问题。
        support=self.method.recall(query)
        temporal=self.temporal.recall(query,current_memory_ids=tuple(item.item_id for item in support.retrieved or ()))
        items=tuple(support.retrieved or ())
        context=support.context
        if temporal.date_target is not None:
            eligible=set(temporal.current_target_ids or ())
            items=tuple(item for item in items if item.item_id in eligible)
            context=("以下当前长期记忆的可证区间覆盖问题指定的日期：\n"+"\n".join("- "+item.content for item in items)) if items else ""
        if temporal.context or temporal.date_target is not None:
            items+=tuple(RetrievedTrace(item.memory_id,item.content,item.source_message_ids,
                temporal_role="historical",valid_from=item.valid_from,valid_to=item.valid_to) for item in temporal.items)
            support=replace(support,context="\n\n".join(value for value in (context,temporal.context) if value),
                retrieved=items,retrieval_strategy="+".join(value for value in (support.retrieval_strategy,temporal.strategy) if value))
        return replace(support,retrieved=tuple(replace(item,source_event_ids=None if item.source_event_ids is None else
            tuple(self.inverse.get(source,source) for source in item.source_event_ids)) for item in support.retrieved or ()))

    def close(self):
        if not self.closed:
            self.runtime.close(); self.temporal.close(); self.closed=True
