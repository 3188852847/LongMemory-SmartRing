"""已有校园请求/响应的禁网回放；输入目录显式提供，正文只留忽略目录。

只替换S2 evidence_list中的一次运行UUID；模型正文、原生meta不改写。
后续新模型调用返回空操作，仅检查实际送入SDK的上下文是否仍含失效材料。
"""

from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re


EXPECTED_CAPTURE_HASHES = {
    "model-3-request.json":"6b9a52d3b6ecd3595508d5198c61d393cd66ef65819caeca5b9561739f378719",
    "model-3-response.json":"e05e16a807ab1a61023faf9deadfafcfbdbf99c66b036f55a2db6b4c20996b01",
    "model-6-request.json":"36e8b0ade8c624179d9c0a6744c0f758618f237cbbe933e20c27bf644c0f6016",
    "model-6-response.json":"ea50bb89bbf809a091e97107e0d63d16b42d92804dfd407fc19604a9f462391e",
    "model-10-request.json":"a91ae5c84cdc977a4b2185fcecd80fa82d73da2d390f4d1538a9e00a13404327",
    "model-10-response.json":"87ada66d785f6a27f0902faa55c6cd69464a6a3cdd08800d7f90de41ee980ea0",
    "model-14-request.json":"68ef9f04878af93c77ab654216cb93e8721038a49546328fae43141716c8ce48",
    "model-14-response.json":"8c64b40532c164131900a4d3b7ab9f2c5cf33dc59b5ab399dd0c717d2bedc0b8",
}


def parsed(content):
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip()))


def run(capture_directory):
    from longmemory.methods.hy_memory import worker
    from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
    from hy_memory.models.memory import MemoryLayer, MemoryNode
    import httpx
    captures = Path(capture_directory)
    seeds = json.loads((captures/"seeds-private.json").read_text(encoding="utf-8"))
    # 使用已有向量的归一化均值，避免把所有新记录与seed0做成相同向量，
    # 导致原生复本压缩/同分截断随机移除待检查的L2；这不是新模型向量证据。
    vector=[sum(row["embedding"][i] for row in seeds)/len(seeds) for i in range(len(seeds[0]["embedding"]))]
    norm=math.sqrt(sum(v*v for v in vector))
    vector=[v/norm for v in vector]
    responses, original_hashes = [], {}
    for i in (3,6,10,14):
        for kind in ("request","response"):
            path = captures/f"raw-models/model-{i}-{kind}.json"
            original_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        responses.append(json.loads((captures/f"raw-models/model-{i}-response.json").read_text(encoding="utf-8")))
    if original_hashes != EXPECTED_CAPTURE_HASHES:
        raise ValueError("ab_replay_capture_hash_mismatch")
    inferred_content = parsed(responses[0]["choices"][0]["message"]["content"])["memory"][0]["content"]
    def factory(settings,workspace,*,create):
        trace = {"original_capture_hashes":original_hashes,"offline_model_calls":0,"external_http_attempts":0,
            "uuid_rebinding":None,"followup_prompts_contain_inferred":[],"followup_prompts_contain_retired_original":[]}
        async def response(request,budget):
            budget.check_management_request(request.url)
            with budget._lock:
                budget.simulated_requests += 1
            body = json.loads(request.content)
            if request.url.path.endswith("/embeddings"):
                inputs = body["input"] if isinstance(body["input"],list) else [body["input"]]
                return httpx.Response(200,json={"data":[{"index":i,"embedding":vector} for i in range(len(inputs))]})
            index = trace["offline_model_calls"]
            trace["offline_model_calls"] += 1
            (workspace/"replay-safe-trace.json").write_text(json.dumps(trace,indent=2),encoding="utf-8")
            prompt = json.dumps(body.get("messages"),ensure_ascii=False)
            if index<4 and create:
                result = json.loads(json.dumps(responses[index]))
                if index==2:
                    nodes = await client._vector_store.list_by_user(user_id=settings.user_id,layers=[MemoryLayer.L2_FACT],limit=20)
                    inferred = [n for n in nodes if n.content==inferred_content]
                    if len(inferred)!=1:
                        raise ValueError("ab_replay_inferred_node_missing")
                    operations=parsed(result["choices"][0]["message"]["content"])
                    old=operations[0]["evidence_list"][-1]
                    operations[0]["evidence_list"][-1]=inferred[0].node_id
                    result["choices"][0]["message"]["content"]=json.dumps(operations,ensure_ascii=False)
                    trace["uuid_rebinding"]={"recorded":old,"replayed":inferred[0].node_id}
            else:
                trace["followup_prompts_contain_inferred"].append(inferred_content in prompt)
                trace["followup_prompts_contain_retired_original"].append(seeds[0]["content"] in prompt)
                content = {"memory":[],"intentions":[],"basic_info":{}} if "intentions" in prompt and "create_schema" not in prompt else []
                result={"choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":json.dumps(content)}}]}
            (workspace/"replay-safe-trace.json").write_text(json.dumps(trace,indent=2),encoding="utf-8")
            return httpx.Response(200,json=result)
        client,budget=worker.create_sdk(settings,workspace,create=create,synthetic_responder=response)
        native_evolve=client.evolve
        def evolve(**kwargs):
            try:
                result=native_evolve(**kwargs)
                (workspace/"replay-evolve.json").write_text(json.dumps(result,default=str),encoding="utf-8")
                return result
            except Exception:
                import traceback
                (workspace/"replay-evolve-error.txt").write_text(traceback.format_exc(),encoding="utf-8")
                raise
        client.evolve=evolve
        if create:
            async def seed():
                for index,row in enumerate(seeds):
                    custom={"meta":[{"namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":[row["event_id"]]}]}
                    for raw in (True,False):
                        await client._vector_store.upsert(MemoryNode(node_id=f"ab-campus-{'raw' if raw else 'fact'}-{index}",
                            user_id=settings.user_id,agent_id=settings.agent_id,source=SOURCE_NAMESPACE,
                            layer=MemoryLayer.L1_RAW if raw else MemoryLayer.L2_FACT,owner="user",content=row["content"],
                            memory_at=datetime(2026,10,1+index*4,tzinfo=UTC),embedding=row["embedding"],
                            custom=custom if raw else {**custom,"source_raw_memory_ids":[f"ab-campus-raw-{index}"]}))
            client._loop_thread.run(seed())
        return client,budget
    worker.main(service=worker.ProtocolService(factory=factory))
