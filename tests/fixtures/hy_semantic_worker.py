"""AB 专用：真实 SDK/Kuzu/Chroma、禁网模型替身、新合成库。"""

import asyncio
from datetime import UTC, datetime, timedelta
import json

from longmemory.methods.hy_memory.worker import ProtocolService, create_sdk, main
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE


def run(scenario="normal"):
    def factory(settings, workspace, *, create):
        import httpx
        async def response(request, budget):
            budget.check_management_request(request.url)
            with budget._lock:
                budget.simulated_requests += 1
            body = json.loads(request.content)
            if request.url.path.endswith("/embeddings"):
                inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                return httpx.Response(200, json={"data": [{"index": i, "object": "embedding",
                    "embedding": [1.0] + [0.0] * (settings.embedding_dimensions-1)} for i in range(len(inputs))]})
            prompt = json.dumps(body.get("messages"), ensure_ascii=False)
            if "create_schema" in prompt:
                if scenario == "slow":
                    (workspace/"ab-delay-active").write_text("synthetic", encoding="utf-8")
                    await asyncio.sleep(2)
                content = json.dumps([{"op": "create_schema", "content": "合成用户在规划前反复核对资料",
                    "evidence_list": ["ab-fact-"+str(i) for i in range(4)], "tags": []}], ensure_ascii=False)
            elif "intentions" in prompt:
                content = json.dumps({"memory": [], "basic_info": {}, "intentions": [{"content": "合成用户计划下周检查资料",
                    "valid_until": "2099-01-01", "owner": "user", "tags": []}]}, ensure_ascii=False)
            else:
                content = "[]"
            return httpx.Response(200, json={"id": "ab-synthetic", "object": "chat.completion", "model": "ab-synthetic",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})
        try:
            client, budget = create_sdk(settings, workspace, create=create, synthetic_responder=response)
        except Exception:
            import traceback
            (workspace/"ab-test-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
            raise
        original_evolve = client.evolve
        def observed_evolve(**kwargs):
            import faulthandler
            trace = (workspace/"ab-test-stacks.txt").open("w",encoding="utf-8")
            faulthandler.dump_traceback_later(15, file=trace)
            try:
                if scenario == "blocked_write_loop":
                    # 人工阻塞SDK写loop，检验整个回答读取链没有回跳它。
                    async def blocked():
                        import time
                        (workspace/"ab-delay-active").write_text("synthetic",encoding="utf-8")
                        time.sleep(2)
                        return await client.async_evolve(**kwargs)
                    result = client._loop_thread.run(blocked())
                else:
                    result = original_evolve(**kwargs)
                (workspace/"ab-test-evolve.json").write_text(json.dumps({key:result.get(key) for key in
                    ("success","request_id","cycle_status","should_continue","elapsed_ms")},ensure_ascii=False),encoding="utf-8")
                return result
            except Exception:
                import traceback
                (workspace/"ab-test-evolve-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
                raise
            finally:
                faulthandler.cancel_dump_traceback_later()
                trace.close()
        client.evolve = observed_evolve
        if create:
            from hy_memory.models.memory import MemoryNode, MemoryLayer, MemoryStatus
            async def seed():
                now = datetime.now(UTC)
                await client._vector_store.upsert(MemoryNode(node_id="ab-profile",user_id=settings.user_id,
                    agent_id="",source="default",layer=MemoryLayer.L0_BASIC_INFO,content="合成姓名",
                    embedding=[1.0]+[0.0]*(settings.embedding_dimensions-1),custom={"basic_info_kv":{"name":"合成小明"},
                        "meta":[{"namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":["ab-profile-source"]}]}))
                if scenario != "projection":
                    await client._vector_store.upsert(MemoryNode(node_id="ab-old",user_id=settings.user_id,
                        agent_id=settings.agent_id,source=SOURCE_NAMESPACE,layer=MemoryLayer.L2_FACT,content="合成历史规划事实",
                        status=MemoryStatus.SUPERSEDED,is_latest=False,superseded_by=["ab-fact-0"],
                        embedding=[1.0]+[0.0]*(settings.embedding_dimensions-1),custom={"meta":[{
                            "namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":["ab-old-source"]}]}))
                for i in range(4):
                    meta = {"meta": [{"namespace": SOURCE_NAMESPACE, "role": "user", "source_event_ids": ["ab-source-"+str(i)]}]}
                    await client._vector_store.upsert(MemoryNode(node_id="ab-raw-"+str(i), user_id=settings.user_id,
                        agent_id=settings.agent_id, source=SOURCE_NAMESPACE, layer=MemoryLayer.L1_RAW, content="合成原话"+str(i),
                        embedding=[1.0]+[0.0]*(settings.embedding_dimensions-1), custom=meta))
                    vector = [0.8]+[0.0]*(settings.embedding_dimensions-1)
                    vector[i+1] = 0.6
                    await client._vector_store.upsert(MemoryNode(node_id="ab-fact-"+str(i), user_id=settings.user_id,
                        agent_id=settings.agent_id, source=SOURCE_NAMESPACE, layer=MemoryLayer.L2_FACT, owner="user",
                        supersedes=["ab-old"] if i == 0 and scenario != "projection" else None,
                        content="合成规划核查事实"+str(i), embedding=vector, memory_at=now,
                        custom={**meta,"source_raw_memory_ids":["ab-raw-"+str(i)]}))
                for name, delta in (("live", 7), ("expired", -1)):
                    await client._vector_store.upsert(MemoryNode(node_id="ab-intention-"+name, user_id=settings.user_id,
                        agent_id=settings.agent_id, source=SOURCE_NAMESPACE, layer=MemoryLayer.L7_INTENTION,
                        content="合成待办"+name, embedding=[1.0]+[0.0]*(settings.embedding_dimensions-1), memory_at=now,
                        valid_until=now+timedelta(days=delta), custom={"meta":[{"namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":["ab-source-0"]}]}))
            try:
                client._loop_thread.run(seed())
            except Exception:
                import traceback
                (workspace/"ab-test-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
                raise
        return client, budget
    main(service=ProtocolService(factory=factory))
