"""来源门不凭关键词判断真伪，不能被旧meta/旧RAW/重启绕过。"""

import asyncio
from types import SimpleNamespace as NS
import sqlite3
import pytest

from longmemory.methods.hy_memory.provenance import ProvenanceGuard, INFERENCE_PREFIX, INTENTION_INFERENCE_PREFIX
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE


def node(identifier, content, *, layer="l2_fact", source="event", raw=None):
    return NS(node_id=identifier,content=content,user_id="u",agent_id="a",source=SOURCE_NAMESPACE,
        layer=NS(value=layer),source_raw_memory_id=raw,custom={"meta":[{
            "namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":[source]}]})


class Store:
    def __init__(self, nodes):
        self.nodes = {n.node_id:n for n in nodes}
    async def get_by_id(self, identifier):
        return self.nodes.get(identifier)
    async def list_by_user(self, **kwargs):
        return list(self.nodes.values())
    async def search(self, **kwargs):
        return [{"node":n} for n in self.nodes.values()]
    async def upsert(self, node):
        self.nodes[node.node_id] = node
        return node.node_id
    async def upsert_batch(self, nodes):
        for n in nodes:
            await self.upsert(n)


def setup(tmp_path):
    literal = node("quote","我没有核对习惯。",source="old",raw="raw")
    raw = node("raw",literal.content,source="old",layer="l1_raw")
    unrelated = node("unrelated","我喜欢蓝色。",source="other",raw="raw-other")
    raw_other = node("raw-other",unrelated.content,source="other",layer="l1_raw")
    # meta只有新事件，正文却概括旧上下文；无关键字分类器。
    unknown = node("legacy","模型概括A。",source="future",raw="raw")
    store, budget = Store([raw,literal,raw_other,unrelated,unknown]), NS(operation=None)
    client = NS(_vector_store=store)
    guard = ProvenanceGuard(client,NS(user_id="u",agent_id="a"),budget,tmp_path)
    return store,budget,guard,literal,unknown


def test_new_inference_tracks_context_without_forging_semantic_sources(tmp_path):
    async def run():
        store,budget,guard,literal,_ = setup(tmp_path)
        arguments = {"request_id":"future","data":[{"role":"user","content":"新计划。"}]}
        state = await guard.begin_add(arguments)
        token = guard.capture.set(state)
        try:
            inferred = node("derived","跨场景概括。",source="future")
            await store.upsert(inferred)
            same = node("direct","新计划。",source="future")
            await store.upsert(same)
        finally:
            guard.end_add(token)
        assert guard.sources(inferred)==("future",)
        assert (await guard.describe(inferred))["semantic_source_complete"] is False
        assert (await guard.describe(inferred))["dependency_basis"]=="scope_context_envelope"
        assert (await guard.describe(same))["semantic_source_complete"] is True
        assert (await guard.project(inferred,inferred.content)).startswith(INFERENCE_PREFIX)
        assert await guard.project(literal,literal.content)==literal.content
        guard.invalidate({"memory_id":"quote","meta":literal.custom["meta"]},"delete")
        assert not await guard.allowed(inferred)
        # 原话不借历史上下文决定语义；它仍可使用自己的当前事件。
        assert await guard.allowed(same)
    asyncio.run(run())


def test_legacy_unknown_and_old_raw_isolated_but_unrelated_exact_quote_survives(tmp_path):
    async def run():
        store,budget,guard,literal,unknown = setup(tmp_path)
        assert await guard.allowed(unknown)
        assert (await guard.project(unknown,unknown.content)).startswith(INFERENCE_PREFIX)
        guard.invalidate({"memory_id":"quote","meta":literal.custom["meta"]},"delete")
        assert await store.get_by_id("raw") is None
        assert await store.get_by_id("legacy") is None
        assert await store.get_by_id("unrelated") is not None
        budget.operation="get"
        assert await store.get_by_id("legacy") is unknown  # 审计仍保留原记录
        # 重启后隔离不丢失；没有SDK原生批量改写。
        reopened = ProvenanceGuard(NS(_vector_store=Store(list(store.nodes.values()))),NS(user_id="u",agent_id="a"),NS(operation=None),tmp_path)
        assert not await reopened.allowed(unknown)
        assert await reopened.literal(literal)
    asyncio.run(run())


def test_full_quote_equality_preserves_negation_and_rejects_substring(tmp_path):
    async def run():
        _,_,guard,literal,_ = setup(tmp_path)
        assert await guard.literal(literal)
        altered=node("opposite","我有核对习惯。",source="old",raw="raw")
        assert not await guard.literal(altered)
        assert not await guard.literal(node("substring","核对习惯",source="old",raw="raw"))
    asyncio.run(run())


def test_correction_requires_completed_audit_and_exact_new_hash(tmp_path):
    async def run():
        store,budget,guard,literal,_=setup(tmp_path)
        guard.invalidate({"memory_id":"quote","meta":literal.custom["meta"]},"update","新的用户纠正。")
        literal.content="新的用户纠正。"
        assert not await guard.allowed(literal)
        with sqlite3.connect(guard.audit) as db:
            db.execute("CREATE TABLE operations(item_id,source_event_id,state,action)")
            db.execute("INSERT INTO operations VALUES ('quote','hy-management:req','uncertain','correct')")
        assert not await guard.allowed(literal)
        with sqlite3.connect(guard.audit) as db:
            db.execute("UPDATE operations SET state='completed'")
        assert await guard.allowed(literal)
        assert await guard.project(literal,literal.content)==literal.content
        capture=await guard.begin_add({"request_id":"next","data":[{"role":"user","content":"下一条。"}]})
        assert "source:hy-management:req" in capture[0] and "node:quote" in capture[0]
        assert "source:old" not in capture[0]
        literal.content="未经核验的其他内容。"
        assert not await guard.allowed(literal)
    asyncio.run(run())


def test_batch_capture_uses_one_ledger_connection_and_keeps_scope_bound(tmp_path,monkeypatch):
    async def run():
        store,_,guard,_,_=setup(tmp_path)
        for i in range(1000):
            item=node("batch-"+str(i),"合成概括"+str(i),source="event-"+str(i))
            store.nodes[item.node_id]=item
        original=sqlite3.connect
        connects=[]
        def connect(*args,**kwargs):
            connects.append(args[0])
            return original(*args,**kwargs)
        monkeypatch.setattr(sqlite3,"connect",connect)
        state=await guard.begin_add({"request_id":"next","data":[{"role":"user","content":"下一条。"}]})
        assert len(connects)==1
        assert all("node:batch-"+str(i) in state[0] and "source:event-"+str(i) in state[0] for i in range(1000))
        assert "legacy:unverified" in state[0]
        assert guard.diagnostics()["node_count"]==1005
        from longmemory.methods.hy_memory import provenance
        monkeypatch.setattr(provenance,"LIMIT",1000)
        with pytest.raises(ValueError,match="context_envelope_unproven"):
            await guard.begin_add({"request_id":"over","data":[]})
        assert len(connects)==1  # 超过上限先拒绝，不提取/落库/新开账本。
    asyncio.run(run())


def test_direct_dependency_edges_keep_transitive_invalidation_without_flattening(tmp_path):
    async def run():
        store,_,guard,literal,_=setup(tmp_path)
        store.nodes.pop("legacy")
        for name in ("b","c"):
            state=await guard.begin_add({"request_id":name,"data":[{"role":"user","content":"另一条输入"+name}]})
            token=guard.capture.set(state)
            try:
                await store.upsert(node(name,"模型生成"+name,source=name))
            finally:
                guard.end_add(token)
            if name=="b":
                store.nodes.pop("raw");store.nodes.pop("quote")
        assert "source:old" not in state[0] and "node:b" in state[0]
        guard.invalidate({"memory_id":"quote","meta":literal.custom["meta"]},"delete")
        assert not await guard.allowed(store.nodes["b"]) and not await guard.allowed(store.nodes["c"])
    asyncio.run(run())


def test_unverified_intention_and_empty_schema_keep_explicit_origin_warning(tmp_path):
    async def run():
        _,_,guard,_,_=setup(tmp_path)
        intention=node("intention","未来安排",layer="l7_intention",source="future")
        projected=await guard.project_intention(intention,intention.content)
        assert projected.startswith(INTENTION_INFERENCE_PREFIX)
        assert await guard.project_intention(intention,projected)==projected
        assert "语义来源尚未证实完整" in await guard.project_schema([],"无证据的模型输出")
        profile=node("profile","name=甲",layer="l0_basic_info")
        profile.agent_id="";profile.source="default"
        status=guard.profile_description([profile])
        assert status["semantic_source_complete"] is False and status["status"]=="model_inference_unverified"
    asyncio.run(run())


def test_snapshot_admission_matches_single_record_gate_before_and_after_management(tmp_path):
    async def run():
        store,_,guard,literal,_=setup(tmp_path)
        for managed in (False,True):
            if managed:
                guard.invalidate({"memory_id":"quote","meta":literal.custom["meta"]},"delete")
            nodes=list(store.nodes.values())
            snapshot=guard.ledger_snapshot(nodes)
            by_id={n.node_id:n for n in nodes}
            for n in nodes:
                assert guard.allowed_from(n,snapshot,by_id)==await guard.allowed(n)
    asyncio.run(run())
