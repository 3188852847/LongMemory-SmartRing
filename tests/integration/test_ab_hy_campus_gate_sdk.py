"""SDK→真实回环HTTP→硬门→供应商替身；零学校/付费调用。"""

from dataclasses import replace
from datetime import UTC,datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from time import monotonic,sleep
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tests/fixtures"))
from ab_hy_campus_gate import HardGate,gateway_type
from hy_campus_probe_support import limited_campus_calls
from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.assembly import assemble_hy_backend,management_primitives_identity
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.settings import HySettings,Endpoint
from longmemory.methods.contracts import MemoryEvent

SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON","missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(),reason="explicit fixed SDK interpreter required")


def test_real_sdk_one_add_auto_evolve_stays_inside_persistent_hard_gate(tmp_path):
    gate = HardGate(tmp_path/"gate.sqlite3",create=True)
    model = ModelSettings(provider="openai_compatible",base_url="https://blocked.invalid",api_key="synthetic",
        model="synthetic-campus",timeout_seconds=2)
    budget = limited_campus_calls(FreeCampusCalls,tmp_path/"free.db",{"request_model":model.model},create=True,arm="candidate",limit=6)
    encoder = SimpleNamespace(identity="f"*64,encode_documents=lambda texts:[[1.0]+[0.0]*7 for _ in texts])
    sent = []
    def remote(payload):
        body = json.loads(payload)
        sent.append(body)
        prompt = json.dumps(body["messages"])
        if "create_schema" in prompt:
            content = json.dumps([{"op":"create_schema","content":"合成用户习惯核查","tags":[],
                "evidence_list":[f"ab-campus-fact-{i}" for i in range(4)]}])
        elif "intentions" in prompt:
            content = json.dumps({"memory":[],"basic_info":{},"intentions":[{"content":"合成未来计划","valid_until":"2099-01-01","owner":"user","tags":[]}]})
        else:
            content="[]"
        return 200,json.dumps({"model":model.model,"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":content}}],
            "usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}).encode()
    gateway = gateway_type(ModelGateway)(gate=gate,raw_directory=tmp_path,settings=model,budget=budget,encoder=encoder,
        free_policy_verified=True,remote=remote)
    gateway.__enter__()
    assembly = None
    try:
        seeds=[]
        for i in range(4):
            vector=[.8]+[0.0]*7
            vector[i+1]=.6
            seeds.append({"event_id":f"seed-{i}","content":f"合成核查事实{i}","embedding":vector})
        seed_path=tmp_path/"seeds.json"
        seed_path.write_text(json.dumps(seeds),encoding="utf-8")
        settings = HySettings(user_id="ab-mock-campus",agent_id="ab-mock-agent",model_mode="disabled",network_authorized=True,
            semantic_layers_enabled=True,max_external_requests=38,max_output_tokens=512,timeout_seconds=5,
            managed_gateway=True,provider_identity="d"*64,
            llm=Endpoint(gateway.base+"/hy/v1",model.model,gateway.token,True),embedding=Endpoint(gateway.base+"/hy/v1",encoder.identity,gateway.token,True))
        def factory(workspace,*,create):
            script=("import sys;sys.path.insert(0,"+repr(str(ROOT/"src"))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");"
                "from ab_hy_semantic_campus import run_sdk;run_sdk("+repr(str(gate.path))+","+repr(str(seed_path))+")")
            return HyProcessClient(python=SDK,workspace=workspace,settings=replace(settings,management_writes_enabled=True,management_exclusive_profile=True),
                create=create,command=[str(SDK),"-I","-X","utf8","-B","-c",script])
        assembly=assemble_hy_backend(settings=settings,state_directory=tmp_path/"engine",source_path=tmp_path/"sources.db",create=True,
            client_factory=factory,management_verification={"protocol":2,"sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),
                "real_sdk_rpc_verified":True,"semantic_background_writes":"managed_v1","derivation_invalidation_verified":True,"read_only_intention_verified":True})
        event=MemoryEvent("ab-mock-future","user","合成未来计划",datetime.now(UTC),"ab-mock")
        result=assembly.method.observe(event)
        assert result.processing_status=="completed"
        engine=assembly.method.engine
        identifier="add:"+hashlib.sha256(event.event_id.encode()).hexdigest()
        deadline=monotonic()+25
        while monotonic()<deadline:
            task=engine.sdk_call("semantic_task",task_id=identifier)
            if task["state"] not in {"pending","running"}:
                break
            sleep(.05)
        assert task["state"]=="completed",task
        state=gate.snapshot()
        assert 1<=state["actual_llm_attempts"]<=6 and state["http_attempts"]<=38 and not state["halted"]
        assert all(body["max_tokens"]<=512 for body in sent)
        assert state["actual_llm_attempts"]==len(sent)
        diagnostics=engine.sdk_call("diagnostics")
        assert diagnostics["local_gateway_requests"]+len(sent)==state["http_attempts"]
        assert all(row["state"]=="completed" for row in state["attempts"])
        assert (tmp_path/"engine/native-add.json").is_file() and (tmp_path/"engine/native-evolve-result.json").is_file()
    finally:
        if assembly:
            assembly.method.close()
        gateway.close()
