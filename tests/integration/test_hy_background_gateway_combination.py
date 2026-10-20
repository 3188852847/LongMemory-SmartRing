"""实际SDK任务＋真实受控网关/HTTP供应商替身；不访问日用或学校。"""

import asyncio
from dataclasses import replace
from datetime import UTC,datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Event,Thread
from time import monotonic
from types import SimpleNamespace

from aiohttp import ClientSession
import pytest

from longmemory.bootstrap import build_backend_runtime
from longmemory.bootstrap_hy_daily import OwnedHyModels
from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.assembly import assemble_hy_backend,management_primitives_identity
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.settings import Endpoint,HySettings

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests/unit/methods"))
from test_hy_candidate_response import body,complete_wire,consume,USAGE

SDK=Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON","missing-owner-sdk"))
pytestmark=pytest.mark.skipif(not SDK.is_file(),reason="explicit owner-installed fixed SDK required")


def test_actual_sdk_pending_advice_and_background_route_preserve_foreground_model_priority(tmp_path):
    entered,release=Event(),Event()
    supplier_order=[]
    class Supplier(BaseHTTPRequestHandler):
        protocol_version="HTTP/1.1"
        def log_message(self,*_args):pass
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            prompt=json.dumps(value.get("messages"),ensure_ascii=False)
            if "__hold__" in prompt:
                supplier_order.append("inflight-background")
                entered.set()
                assert release.wait(10)
                result=[]
            elif value.get("stream"):
                supplier_order.append("formal-answer")
                result=None
            elif "create_schema" in prompt:
                supplier_order.append("native-evolve")
                result=[{"op":"create_schema","content":"合成核对习惯","tags":[],
                    "evidence_list":[f"ab-fact-{i}" for i in range(4)]}]
            elif "intentions" in prompt:
                supplier_order.append("native-add")
                result={"memory":[],"intentions":[],"basic_info":{}}
            else:
                supplier_order.append("native-other")
                result=[]
            payload=(complete_wire() if value.get("stream") else json.dumps({"choices":[{"index":0,
                "finish_reason":"stop","message":{"role":"assistant","content":json.dumps(result,ensure_ascii=False)}}],
                "usage":USAGE},ensure_ascii=False).encode())
            self.send_response(200)
            self.send_header("Content-Type","text/event-stream" if value.get("stream") else "application/json")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload);self.wfile.flush()
    supplier=ThreadingHTTPServer(("127.0.0.1",0),Supplier)
    supplier.daemon_threads=True
    assert supplier.server_port not in {8766,8767,8000,8003,18770}
    thread=Thread(target=lambda:supplier.serve_forever(poll_interval=.01),daemon=True)
    thread.start()
    url=f"http://127.0.0.1:{supplier.server_port}/v1"
    settings=ModelSettings(provider="openai_compatible",base_url=url,api_key="synthetic-owned-key",
        model="DeepSeek-V4-Flash",allow_http=True,timeout_seconds=5)
    proof={"version":1,"profile":"campus","billing_mode":"owner_confirmed_free","personal_cost_micro_cny":0,
        "source":"owner_confirmation","confirmed_date":"2026-10-19","endpoint_sha256":sha256(url.encode()).hexdigest(),
        "request_model":settings.model,"credential_sha256":sha256(settings.api_key.encode()).hexdigest(),
        "ledger_path":"data/databases/synthetic-background.sqlite3"}
    ledger=FreeCampusCalls(tmp_path/"calls.sqlite3",proof=proof,create=True)
    encoder=SimpleNamespace(identity="f"*64,encode_query=lambda _text:[1.0]+[0.0]*7,
        encode_documents=lambda texts:[[1.0]+[0.0]*7 for _ in texts])
    model=ModelGateway(settings=settings,budget=ledger,encoder=encoder,free_policy_verified=True)
    runtime=None
    try:
        model.__enter__()
        prototype=HySettings(user_id="ai-background-sdk",agent_id="ai-background",managed_gateway=True,provider_identity="b"*64,
            llm=Endpoint(model.base+"/hy/v1",settings.model,model.token,True),
            embedding=Endpoint(model.base+"/hy/v1",encoder.identity,model.token,True),network_authorized=True,
            semantic_layers_enabled=True,background_priority_enabled=True,embedding_dimensions=8,max_external_requests=200)
        script="import sys;sys.path.insert(0,"+repr(str(ROOT/"src"))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");from hy_semantic_worker import run;run('projection')"
        def factory(workspace,*,create):
            return HyProcessClient(python=SDK,workspace=workspace,settings=replace(prototype,
                management_writes_enabled=True,management_exclusive_profile=True),create=create,
                command=[str(SDK),"-I","-X","utf8","-B","-c",script])
        verification={"protocol":2,"sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),
            "real_sdk_rpc_verified":True,"semantic_background_writes":"managed_v1","derivation_invalidation_verified":True,
            "read_only_intention_verified":True}
        assembly=assemble_hy_backend(settings=prototype,state_directory=tmp_path/"engine",source_path=tmp_path/"sources.db",
            create=True,client_factory=factory,management_verification=verification)
        runtime=build_backend_runtime(assembly)
        runtime.attach_model_service(OwnedHyModels(model,ledger))
        engine=assembly.method.engine
        async def until(predicate):
            deadline=monotonic()+30
            while not predicate():
                assert monotonic()<deadline
                await asyncio.sleep(.01)
        async def run():
            hold={"model":settings.model,"messages":[{"role":"system","content":"合成角色"},
                {"role":"user","content":"__hold__"}],"stream":False,"max_tokens":256}
            active=asyncio.create_task(asyncio.to_thread(model.complete,"hy",hold,work_class="background"))
            try:
                assert await asyncio.to_thread(entered.wait,2)
                engine.sdk_call("semantic_enqueue",task_id="actual-priority")
                await until(lambda:engine.sdk_call("diagnostics")["background_lane"]["admission_checks"]>=1)
                assert engine.sdk_call("semantic_task",task_id="actual-priority")["state"]=="pending"
                assert ledger.status()["attempt_count"]==1
                assert runtime.candidate_memory_snapshot("检查资料")["engine"]["items"]
                candidate=model.open_candidate_response(body())
                candidate_task=asyncio.create_task(consume(candidate))
                await until(lambda:model._admission.snapshot()["waiting"]["candidate"]==1)
                async with ClientSession(headers={"Authorization":"Bearer "+model.token}) as client:
                    answer=asyncio.create_task(client.post(model.base+"/voice/v1/chat/completions",json=body()))
                    await until(lambda:model._admission.snapshot()["waiting"]["answer"]==1)
                    assert engine.sdk_call("semantic_task",task_id="actual-priority")["state"]=="pending"
                    assert supplier_order==["inflight-background"] and ledger.status()["attempt_count"]==1
                    ack=await candidate.cancel()
                    assert ack["owned_upstream_exited"] and ack["provider_compute_stopped"] is False
                    candidate_task.cancel()
                    await asyncio.gather(candidate_task,return_exceptions=True)
                    release.set()
                    assert (await active)[0]==200
                    response=await answer
                    async with response:
                        assert response.status==200 and b"[DONE]" in await response.read()
                await until(lambda:engine.sdk_call("semantic_task",task_id="actual-priority")["state"] in {"completed","partial"})
                assert supplier_order[:2]==["inflight-background","formal-answer"]
                assert "native-evolve" in supplier_order[2:]
                assert all(row["admission_class"]=="background" for row in model.responses[2:])
                before=len(model.responses)
                event=MemoryEvent("ai-native-front","user","合成前台输入",datetime.now(UTC),"ai-background")
                assert assembly.method.observe(event).processing_status=="completed"
                assert any(row["admission_class"]=="required_hy" for row in model.responses[before:])
                assert engine.sdk_call("diagnostics")["external_http_attempts"]==0
                assert ledger.status()["unknown_or_inflight"]==0
                (tmp_path/"competition.json").write_text(json.dumps({"supplier_order":supplier_order,
                    "model_classes":[row["admission_class"] for row in model.responses],"candidate_reserved":False,
                    "school_calls":0,"actual_sdk":"2.0.3"}),encoding="utf-8")
            finally:
                release.set()
                await asyncio.gather(active,return_exceptions=True)
        asyncio.run(run())
    finally:
        release.set()
        if runtime is not None:runtime.close()
        else:model.close()
        supplier.shutdown();supplier.server_close();thread.join(3)
