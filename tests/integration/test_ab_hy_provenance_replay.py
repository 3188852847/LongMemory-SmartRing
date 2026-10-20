"""显式选择已捕获的忽略目录，无网络、无个人库、无新学校调用。"""

from datetime import UTC,datetime
import hashlib
import json
import os
from pathlib import Path
from time import monotonic,sleep
from uuid import uuid4

import pytest

from longmemory.application.memory_runtime import MemoryRuntime
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.assembly import assemble_hy_backend,management_primitives_identity
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.provenance import INFERENCE_PREFIX
from longmemory.methods.hy_memory.layer_data import validate_result

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON","missing-sdk"))
CAPTURE=Path(os.environ.get("LONGMEMORY_TEST_AB_CAPTURE","missing-capture"))
pytestmark=pytest.mark.skipif(not SDK.is_file() or not CAPTURE.is_dir(),reason="explicit fixed SDK and existing captured responses required")


def open_runtime(tmp_path,*,legacy=False,create=True):
    from dataclasses import replace
    settings=HySettings(user_id="ab-provenance-replay",agent_id="ab-replay",model_mode="synthetic_transport",semantic_layers_enabled=True,
        embedding_dimensions=512)
    source=CAPTURE/"source-5a4c1ec/src" if legacy else ROOT/"src"
    script="import sys;sys.path.insert(0,"+repr(str(source))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");from ab_hy_provenance_replay import run;run("+repr(str(CAPTURE))+")"
    def factory(workspace,*,create):
        return HyProcessClient(python=SDK,workspace=workspace,settings=replace(settings,management_writes_enabled=True,
            management_exclusive_profile=True),create=create,command=[str(SDK),"-I","-X","utf8","-B","-c",script])
    proof={"protocol":2,"sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),"real_sdk_rpc_verified":True,
        "semantic_background_writes":"managed_v1","derivation_invalidation_verified":True,"read_only_intention_verified":True}
    assembly=assemble_hy_backend(settings=settings,state_directory=tmp_path/"engine",source_path=tmp_path/"sources.db",create=create,
        client_factory=factory,management_verification=proof)
    return MemoryRuntime(tmp_path/"sources.db",method=assembly.method,backend_assembly=assembly),assembly


def wait(engine,identifier):
    until=monotonic()+30
    while monotonic()<until:
        task=engine.sdk_call("semantic_task",task_id=identifier)
        if task["state"] not in {"pending","running"}:
            return task
        sleep(.05)
    raise AssertionError("offline replay task timeout")


def replay_add(assembly):
    event=MemoryEvent("ab-campus-future-20261021-01","user",
        "我计划在2026年10月28日上午去图书馆，带齐参考文献后逐项核对报告的页码和引用；这件事还没有执行。",
        datetime(2026,10,20,19,53,tzinfo=UTC),"ab-replay")
    assert assembly.method.observe(event).processing_status=="completed"
    identifier="add:"+hashlib.sha256(event.event_id.encode()).hexdigest()
    assert wait(assembly.method.engine,identifier)["state"]=="completed"
    return event


@pytest.mark.parametrize("action",["correct","delete"])
@pytest.mark.parametrize("mode",["original","guarded","upgrade"])
def test_captured_new_l2_is_inference_and_management_cannot_leave_stale_influence(tmp_path,action,mode):
    legacy=mode in {"original","upgrade"}
    runtime,assembly=open_runtime(tmp_path,legacy=legacy)
    engine=assembly.method.engine
    try:
        event=replay_add(assembly)
        if mode=="upgrade":
            runtime.close()
            runtime,assembly=open_runtime(tmp_path,legacy=False,create=False)
            engine=assembly.method.engine
            legacy=False
        page=engine._client.layer_page(layer="l2_fact",limit=20,offset=0,state="all")
        if not legacy:
            validate_result(page,"layer_page","l2_fact")
        inferred=next(r for r in page["items"] if r["source_event_ids"]==[event.event_id])
        # 精确对应真实收据内容摘要；不把模型正文提交到Git。
        assert hashlib.sha256(inferred["content"].encode()).hexdigest()=="df816339ced67c876fedad75b20f0a2065d53d7916dc8eb22ce1b735ab73f173"
        recalled=engine.recall("核对资料")
        assert any(r.item_id==inferred["item_id"] for r in recalled.retrieved)
        if not legacy:
            row=next(r for r in recalled.retrieved if r.item_id==inferred["item_id"])
            assert INFERENCE_PREFIX in row.content
            assert inferred["provenance"]=={"status":"model_inference_unverified","semantic_source_complete":False,
                "dependency_basis":"legacy_unobserved" if mode=="upgrade" else "scope_context_envelope","injection_allowed":True}
        item=assembly.management.get_item("ab-campus-fact-0")
        request=str(uuid4())
        content="先前记录需要纠正，这次由合成用户明确提交。"
        source=MemoryEvent("hy-management:"+request,"user",content if action=="correct" else "删除这条记忆："+item.item_id,
            datetime.now(UTC),"ab-management")
        result=runtime.administer_extension("hy_memory",action,item_id=item.item_id,request_id=request,
            expected_revision=item.revision,source=source,**({"content":content} if action=="correct" else {}))
        assert result["state"]=="completed"
        assert wait(engine,result["derivation_task_id"])["state"] in {"completed","partial"}
        after=engine.recall("核对资料")
        snapshot=engine.candidate_snapshot(query_embedding=json.loads((CAPTURE/"seeds-private.json").read_text(encoding="utf-8"))[0]["embedding"],limit=10)
        if legacy:
            assert any(r.item_id==inferred["item_id"] for r in after.retrieved)  # 原缺陷真实复现
        else:
            assert all(r.item_id!=inferred["item_id"] for r in after.retrieved)
            assert all(r["memory_id"]!=inferred["item_id"] for r in snapshot["items"])
            assert any("ab-campus-fact-1"==r.item_id for r in after.retrieved)  # 保留无关逐字事实
        # 新add实际经过SDK原生历史读取，不能仅在最终答案处遮挡。
        next_event=MemoryEvent("ab-after-management","user","这是另一条合成输入。",datetime.now(UTC),"ab-next")
        assembly.method.observe(next_event)
        assert wait(engine,"add:"+hashlib.sha256(next_event.event_id.encode()).hexdigest())["state"] in {"completed","partial"}
        trace=json.loads((tmp_path/"engine/replay-safe-trace.json").read_text(encoding="utf-8"))
        assert trace["external_http_attempts"]==0 and engine.sdk_call("diagnostics")["external_http_attempts"]==0
        if not legacy:
            assert trace["followup_prompts_contain_inferred"] and not any(trace["followup_prompts_contain_inferred"])
            assert not any(trace["followup_prompts_contain_retired_original"])
        # 原记录仍可审计，没有批量删除、改写meta或伪造来源。
        assert engine.sdk_call("get",memory_id=inferred["item_id"])["meta"]==[{"namespace":"smartring_synthetic",
            "source_event_ids":[event.event_id],"occurred_at":event.occurred_at.isoformat(),"role":"user"}]
        if not legacy:
            runtime.close()
            runtime,assembly=open_runtime(tmp_path,legacy=False,create=False)
            engine=assembly.method.engine
            assert all(r.item_id!=inferred["item_id"] for r in engine.recall("核对资料").retrieved)
    finally:
        runtime.close()
