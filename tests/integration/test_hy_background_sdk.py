"""真实SDK/HTTP检查后台别名与pending门；远端为本地替身，不访问学校。"""

from dataclasses import replace
from datetime import UTC,datetime
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Event,Lock,Thread
from time import monotonic,sleep

import pytest

from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.assembly import assemble_hy_backend,management_primitives_identity
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.settings import Endpoint,HySettings


ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON","missing-sdk"))
pytestmark=pytest.mark.skipif(not SDK.is_file(),reason="explicit fixed SDK required")


def wait(predicate):
    limit=monotonic()+30
    while monotonic()<limit:
        value=predicate()
        if value:
            return value
        sleep(.03)
    raise AssertionError("synthetic background timeout")


def test_busy_advice_before_task_claim_and_actual_sdk_routes_only_evolve_background(tmp_path):
    ready,checked=Event(),Event()
    lock=Lock()
    paths=[]
    token="ab-local-background-token"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,value):
            data=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def authorized(self):
            return self.headers.get("Authorization")=="Bearer "+token
        def do_GET(self):
            if not self.authorized():
                self.send(401,{});return
            if self.path!="/hy-background/v1/admission":
                self.send(404,{});return
            checked.set()
            self.send(200,{"version":1,"eligible":ready.is_set(),"reason_code":None if ready.is_set() else "model_busy"})
        def do_POST(self):
            if not self.authorized():
                self.send(401,{});return
            body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                paths.append(self.path)
            if self.path=="/hy/v1/embeddings":
                inputs=body["input"] if isinstance(body["input"],list) else [body["input"]]
                self.send(200,{"data":[{"index":i,"embedding":[1.0]+[0.0]*7} for i in range(len(inputs))]})
                return
            prompt=json.dumps(body.get("messages"),ensure_ascii=False)
            if self.path=="/hy-background/v1/chat/completions":
                assert ready.is_set()
                content=[{"op":"create_schema","content":"合成背景检查行为","evidence_list":[f"ab-fact-{i}" for i in range(4)],"tags":[]}] if "create_schema" in prompt else []
            elif self.path=="/hy/v1/chat/completions":
                assert "create_schema" not in prompt
                content={"memory":[],"intentions":[],"basic_info":{}}
            else:
                self.send(404,{});return
            self.send(200,{"choices":[{"index":0,"finish_reason":"stop","message":{
                "role":"assistant","content":json.dumps(content,ensure_ascii=False)}}]})
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    base=f"http://127.0.0.1:{server.server_port}/hy/v1"
    endpoint=Endpoint(base,"synthetic-background-model",token,True)
    prototype=HySettings(user_id="ab-background-sdk",llm=endpoint,embedding=endpoint,network_authorized=True,
        max_external_requests=200,managed_gateway=True,provider_identity="b"*64,semantic_layers_enabled=True,
        background_priority_enabled=True)
    script="import sys;sys.path.insert(0,"+repr(str(ROOT/"src"))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");from hy_semantic_worker import run;run('projection')"
    def factory(workspace,*,create):
        return HyProcessClient(python=SDK,workspace=workspace,settings=replace(prototype,
            management_writes_enabled=True,management_exclusive_profile=True),create=create,
            command=[str(SDK),"-I","-X","utf8","-B","-c",script])
    proof={"protocol":2,"sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),
        "real_sdk_rpc_verified":True,"semantic_background_writes":"managed_v1","derivation_invalidation_verified":True,
        "read_only_intention_verified":True}
    assembly=None
    try:
        assembly=assemble_hy_backend(settings=prototype,state_directory=tmp_path/"engine",source_path=tmp_path/"source.db",
            create=True,client_factory=factory,management_verification=proof)
        engine=assembly.method.engine
        engine.sdk_call("semantic_enqueue",task_id="background-wait")
        assert checked.wait(5)
        assert engine.sdk_call("semantic_task",task_id="background-wait")["state"]=="pending"
        status=engine.sdk_call("semantic_status")
        assert status["management_available"] and status["task_counts"]=={"pending":1}
        assert paths==[]  # 没有模型/embedding调用，更没有模型预算reserve。
        ready.set()
        wait(lambda:engine.sdk_call("semantic_task",task_id="background-wait")["state"]=="completed")
        assert "/hy-background/v1/chat/completions" in paths
        assert "/hy/v1/chat/completions" not in paths
        event=MemoryEvent("ab-background-front","user","合成前台输入。",datetime.now(UTC),"ab-background")
        assert assembly.method.observe(event).processing_status=="completed"
        assert "/hy/v1/chat/completions" in paths
        task="add:"+hashlib.sha256(event.event_id.encode()).hexdigest()
        wait(lambda:engine.sdk_call("semantic_task",task_id=task)["state"] in {"completed","partial"})
        report=engine.sdk_call("diagnostics")
        assert report["external_http_attempts"]==0 and report["background_lane"]["admission_checks"]>=2
        assert report["background_lane"]["admission_reserves_model"] is False
        assert all(p in {"/hy/v1/embeddings","/hy/v1/chat/completions","/hy-background/v1/chat/completions"} for p in paths)
    finally:
        if assembly is not None:
            assembly.method.close()
        server.shutdown();server.server_close();thread.join(timeout=3)
