"""单次授权校园L6/L7探针；真实执行必须显式--execute-campus。"""

import argparse
from dataclasses import replace
from datetime import UTC,datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from threading import Event,Lock,Timer
from time import monotonic,sleep,time,perf_counter
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parent))
from ab_hy_campus_gate import AUTHORIZATION,HTTP_LIMIT,OUTPUT_LIMIT,WALL_SECONDS,HardGate,gateway_type
from hy_campus_probe_support import limited_campus_calls,calls_snapshot


BASE = "5a4c1ecb9abf5d2434f8a6eff2e5b3565d8e5d6a"
ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT.parents[2]
FIXTURES = Path(__file__).resolve().parent
SOURCE_IDS = [f"ab-campus-seed-{i}" for i in range(4)]
SEEDS = [
    "2026年10月1日，合成用户为课程小组制作核对清单，交付前逐项核对引用、表格和附件。",
    "2026年10月5日，合成用户搭建显示终端时先列接线检查步骤，通电前依次核对线序和供电。",
    "2026年10月10日，合成用户准备图书馆报告时建立来源表，发给同伴前逐项复核日期与页码。",
    "2026年10月15日，合成用户安排出行时列文件与交通核对单，出发前交叉检查证件、车次与住宿。",
]
FUTURE_ID = "ab-campus-future-20261021-01"
FUTURE = "我计划在2026年10月28日上午去图书馆，带齐参考文献后逐项核对报告的页码和引用；这件事还没有执行。"
FORBIDDEN_PORTS = {8000,8002,8003,8766,8767,8768,18000,18003,18767,18768,18769,18770}


def write_new(path,value):
    with Path(path).open("x",encoding="utf-8") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,default=str)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def source_snapshot(output):
    if subprocess.check_output(["git","status","--porcelain"],cwd=ROOT).strip():
        raise ValueError("ab_probe_source_must_be_clean")
    target = output/"source-5a4c1ec"
    target.mkdir()
    payload = subprocess.check_output(["git","archive",BASE,"src"],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for entry in archive.getmembers():
            path = target/entry.name
            if not entry.name.startswith("src/") and entry.name!="src":
                raise ValueError("ab_probe_archive_scope")
            if ".." in Path(entry.name).parts or not (entry.isdir() or entry.isfile()):
                raise ValueError("ab_probe_archive_type")
            if entry.isdir():
                path.mkdir(parents=True,exist_ok=True)
            else:
                with path.open("xb") as stream:
                    stream.write(archive.extractfile(entry).read())
    return target


def run_sdk(gate_path,seed_path):
    """在owner SDK子进程安装本次budget包装；不修改任何供应商/SDK源码。"""
    for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        os.environ[name]="2"
    from longmemory.methods.hy_memory import worker
    import asyncio
    from contextvars import ContextVar
    import httpx
    gate = HardGate(gate_path)
    seeds = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    current = ContextVar("ab_sdk_http_attempt",default=None)
    serial = Lock()
    original_send = httpx.AsyncHTTPTransport.handle_async_request
    class SerialStream(httpx.AsyncByteStream):
        def __init__(self,inner,identifier,status):
            self.inner,self.identifier,self.status,self.released = inner,identifier,status,False
        def release(self):
            if not self.released:
                self.released=True
                try:
                    gate.sdk_finished(self.identifier,status=self.status)
                finally:
                    serial.release()
        async def __aiter__(self):
            try:
                async for chunk in self.inner:
                    yield chunk
            finally:
                self.release()
        async def aclose(self):
            try:
                await self.inner.aclose()
            finally:
                self.release()
    async def serial_send(transport,request):
        identifier = current.get()
        if identifier is None:
            raise RuntimeError("ab_probe_unmetered_http_denied")
        await asyncio.to_thread(serial.acquire)
        try:
            response = await original_send(transport,request)
            response.stream = SerialStream(response.stream,identifier,response.status_code)
            return response
        except BaseException:
            serial.release()
            gate.sdk_finished(identifier,status=None)
            raise
    httpx.AsyncHTTPTransport.handle_async_request = serial_send
    def factory(settings,workspace,*,create):
        original_budget = worker.RequestBudget
        class CappedBudget(original_budget):
            def claim(self,url):
                current.set(gate.sdk_claim(url))
                return super().claim(url)
        worker.RequestBudget = CappedBudget
        try:
            client,budget = worker.create_sdk(settings,workspace,create=create)
        finally:
            worker.RequestBudget = original_budget
        if create:
            from hy_memory.models.memory import MemoryLayer,MemoryNode
            from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
            async def seed():
                for index,row in enumerate(seeds):
                    moment = datetime(2026,10,1+index*4,tzinfo=UTC)
                    custom = {"meta":[{"namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":[row["event_id"]]}]}
                    await client._vector_store.upsert(MemoryNode(node_id=f"ab-campus-raw-{index}",user_id=settings.user_id,
                        agent_id=settings.agent_id,source=SOURCE_NAMESPACE,layer=MemoryLayer.L1_RAW,content=row["content"],
                        memory_at=moment,embedding=row["embedding"],custom=custom))
                    await client._vector_store.upsert(MemoryNode(node_id=f"ab-campus-fact-{index}",user_id=settings.user_id,
                        agent_id=settings.agent_id,source=SOURCE_NAMESPACE,layer=MemoryLayer.L2_FACT,owner="user",
                        content=row["content"],memory_at=moment,embedding=row["embedding"],
                        custom={**custom,"source_raw_memory_ids":[f"ab-campus-raw-{index}"]}))
            client._loop_thread.run(seed())
        add,evolve = client.add,client.evolve
        def once_add(*args,**kwargs):
            write_new(workspace/"native-add.json",{"request_id":kwargs.get("request_id"),"count":1})
            return add(*args,**kwargs)
        def once_evolve(**kwargs):
            if kwargs.get("max_batches")!=1:
                raise ValueError("ab_probe_evolve_batch_denied")
            write_new(workspace/"native-evolve.json",{"max_batches":1,"count":1,"started_at":time()})
            result = evolve(**kwargs)
            write_new(workspace/"native-evolve-result.json",{key:result.get(key) for key in
                ("success","cycle_status","should_continue","elapsed_ms","tasks_processed")})
            return result
        client.add,client.evolve = once_add,once_evolve
        return client,budget
    worker.main(service=worker.ProtocolService(factory=factory))


def safe_layers(engine):
    result = {}
    for layer in ("l1_raw","l2_fact","l6_schema","l7_intention"):
        page = engine._client.layer_page(layer=layer,limit=20,offset=0,state="all")
        result[layer] = {key:page[key] for key in ("generation_state","read_status","coverage","data_state","total","has_more")}
        result[layer]["items"] = [{key:row.get(key) for key in ("item_id","status","semantic_kind","derivation_state",
            "source_event_ids","valid_until","evidence_memory_ids")} | {"content_chars":len(row["content"]),
            "content_sha256":hashlib.sha256(row["content"].encode()).hexdigest()} for row in page["items"]]
    return result


def run_child(config):
    output,owner,source = map(Path,(config["output"],config["owner"],config["source"]))
    sys.path.insert(0,str(source/"src"))
    import longmemory
    if not Path(longmemory.__file__).resolve().is_relative_to(source/"src"):
        raise ValueError("ab_probe_import_source_mismatch")
    from longmemory.bootstrap_hy_daily import load_daily_encoder
    from longmemory.methods.hy_memory.model_gateway import ModelGateway,selected_model
    from longmemory.methods.hy_memory.assembly import assemble_hy_backend,management_primitives_identity
    from longmemory.methods.hy_memory.process_client import HyProcessClient
    from longmemory.methods.hy_memory.settings import Endpoint
    from longmemory.infrastructure.config.hy_deployment import load_hy_deployment
    from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
    from longmemory.methods.contracts import MemoryEvent
    from hy_campus_latency_probe import campus_policy
    gate = HardGate(output/"gate.sqlite3")
    model,model_identity = selected_model(owner)
    if model_identity.get("profile")!="campus":
        raise ValueError("ab_probe_campus_only")
    address = urlsplit(model.base_url)
    if address.hostname in {"localhost","127.0.0.1","::1"} and address.port in FORBIDDEN_PORTS:
        raise ValueError("ab_probe_daily_port_denied")
    policy = campus_policy(owner,model)
    policy["ledger_path"]="data/databases/"+AUTHORIZATION+".sqlite3"
    deployment = load_hy_deployment(owner)
    if deployment.python!=Path(config["sdk_python"]).resolve():
        raise ValueError("ab_probe_interpreter_mismatch")
    protected_names = ("local/config/.env","local/config/preferences/model-profile.json","local/config/hy-memory/provider-policy.json",
        "local/config/hy-memory/deployment.json","local/config/hy-memory/settings.json","local/config/hy-memory/management-verification.json")
    protected = {name:sha(owner/name) for name in protected_names if (owner/name).is_file()}
    write_new(output/"protected-before.json",protected)
    budget = limited_campus_calls(FreeCampusCalls,output/"free-campus.sqlite3",policy,create=True,arm="candidate",limit=6)
    # 不读原付费/校园账本，只使用上面的新FreeCampus文件。
    started = perf_counter()
    encoder = load_daily_encoder(owner)
    encoder._torch.set_num_threads(2)
    encoder._torch.set_num_interop_threads(2)
    vectors = encoder.encode_documents(SEEDS)
    seeds = [{"event_id":identifier,"content":content,"embedding":vector} for identifier,content,vector in zip(SOURCE_IDS,SEEDS,vectors)]
    write_new(output/"seeds-private.json",seeds)
    encoder_ms = (perf_counter()-started)*1000
    if encoder.metadata.get("device")!="cpu" or encoder._torch.get_num_threads()!=2:
        raise ValueError("ab_probe_cpu_required")
    raw = output/"raw-models"
    raw.mkdir()
    gateway = gateway_type(ModelGateway)(gate=gate,raw_directory=raw,settings=replace(model,timeout_seconds=min(30,model.timeout_seconds)),
        budget=budget,encoder=encoder,free_policy_verified=True)
    if gateway.server.server_port in FORBIDDEN_PORTS:
        gateway.close()
        raise ValueError("ab_probe_gateway_daily_port_denied")
    assembly = None
    report = {"authorization":AUTHORIZATION,"source_commit":BASE,"harness_commit":config["harness_commit"],
        "rpc_source_sha256":management_primitives_identity(),"billing_policy":"owner_confirmed_free","personal_cost_micro_cny":0,
        "mode":"real_campus","model_identity":model_identity,"encoder_identity":encoder.identity,"encoder_cpu_threads":2,
        "encoder_load_ms":round(encoder_ms,3),"native_add_requested":1,"manual_evolve_requested":0}
    try:
        gateway.__enter__()
        prototype = deployment.settings
        provider = hashlib.sha256(json.dumps({"model":model_identity,"embedding":encoder.identity},sort_keys=True).encode()).hexdigest()
        if prototype.embedding.model!=encoder.identity or prototype.provider_identity!=provider:
            raise ValueError("ab_probe_provider_identity_mismatch")
        settings = replace(prototype,user_id="ab-campus-synthetic-20261021",agent_id="ab-campus-agent",
            llm=Endpoint(gateway.base+"/hy/v1",model.model,gateway.token,True),embedding=Endpoint(gateway.base+"/hy/v1",encoder.identity,gateway.token,True),
            semantic_layers_enabled=True,max_external_requests=HTTP_LIMIT,max_output_tokens=OUTPUT_LIMIT,timeout_seconds=30)
        def factory(workspace,*,create):
            script = ("import sys;sys.path.insert(0,"+repr(str(source/"src"))+");sys.path.insert(0,"+repr(str(FIXTURES))+");"
                "from ab_hy_semantic_campus import run_sdk;run_sdk("+repr(str(output/"gate.sqlite3"))+","+repr(str(output/"seeds-private.json"))+")")
            from dataclasses import replace as copy_settings
            return HyProcessClient(python=Path(config["sdk_python"]),workspace=workspace,
                settings=copy_settings(settings,management_writes_enabled=True,management_exclusive_profile=True),create=create,
                command=[config["sdk_python"],"-I","-X","utf8","-B","-c",script])
        proof = {"protocol":2,"sdk_version":"2.0.3","rpc_source_sha256":report["rpc_source_sha256"],"real_sdk_rpc_verified":True,
            "semantic_background_writes":"managed_v1","derivation_invalidation_verified":True,"read_only_intention_verified":True}
        assembly = assemble_hy_backend(settings=settings,state_directory=output/"engine",source_path=output/"sources.sqlite3",
            create=True,client_factory=factory,management_verification=proof,expected_python_version="3.12.13")
        engine = assembly.method.engine
        for index,row in enumerate(seeds):
            assembly.method.archive(MemoryEvent(row["event_id"],"user",row["content"],datetime(2026,10,1+index*4,tzinfo=UTC),"ab-campus-seeds"))
        event = MemoryEvent(FUTURE_ID,"user",FUTURE,datetime(2026,10,21,tzinfo=UTC),"ab-campus-future")
        started = perf_counter()
        observation = assembly.method.observe(event)
        report["observe_elapsed_ms"] = round((perf_counter()-started)*1000,3)
        report["source_state"] = assembly.method.source_status(event.event_id)["state"]
        report["processing_status"] = observation.processing_status
        identifier = "add:"+hashlib.sha256(event.event_id.encode()).hexdigest()
        if observation.processing_status=="completed":
            while True:
                if gate.snapshot()["halted"]:
                    raise RuntimeError("ab_probe_gate_halted")
                task = engine.sdk_call("semantic_task",task_id=identifier)
                if task["state"] not in {"pending","running"}:
                    report["evolve_task"] = task
                    break
                sleep(.05)
        report["layers"] = safe_layers(engine)
        report["semantic_status"] = engine.sdk_call("semantic_status")
        diagnostics = engine.sdk_call("diagnostics")
        report["sdk_diagnostics"] = {key:diagnostics.get(key) for key in
            ("actual_sdk_version","sdk_python","external_http_attempts","local_gateway_requests","simulated_model_requests","semantic_local_prepared_ms")}
        report["free_calls"] = calls_snapshot(output/"free-campus.sqlite3")
        report["usage"] = [{"attempt_id":row["attempt_id"],"http_status":row["http_status"],"response_model":row["response_model"],
            "finish_reason":row["finish_reason"],"usage":{key:(row["usage"] or {}).get(key) for key in
                ("prompt_tokens","completion_tokens","total_tokens","prompt_cache_hit_tokens","prompt_cache_miss_tokens")}} for row in gateway.responses]
        report["status"] = "completed" if observation.processing_status=="completed" else "partial"
        report["owner_configuration_unchanged"] = all(sha(owner/name)==value for name,value in protected.items())
        report["l6_generated"] = bool(report["layers"]["l6_schema"]["items"])
        report["l7_generated"] = any(FUTURE_ID in (row.get("source_event_ids") or []) for row in report["layers"]["l7_intention"]["items"])
        write_new(output/"receipt.json",report)
    except BaseException as error:
        gate.halt("probe_failed")
        report.update(status="partial",reason_code="ab_probe_"+type(error).__name__)
        if not (output/"receipt.json").exists():
            write_new(output/"receipt.json",report)
    finally:
        if assembly is not None:
            try:
                # 失败不让仍运行的SDK继续取样；只结束此实例创建的子进程。
                if report.get("status")!="completed":
                    assembly.method.engine._client.client._stop()
                assembly.method.close()
            except Exception:
                pass
        gateway.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--execute-campus",action="store_true")
    parser.add_argument("--sdk-python",type=Path)
    args = parser.parse_args()
    if args.worker:
        config = json.loads(sys.stdin.buffer.readline())
        try:
            run_child(config)
        except BaseException as error:
            path = Path(config["output"])/"worker-failure.json"
            if not path.exists():
                write_new(path,{"error_type":type(error).__name__,"code":str(error) if str(error).startswith("ab_probe_") else "pre_run_failure"})
            import traceback
            (Path(config["output"])/"worker-failure-private.txt").write_text(traceback.format_exc(),encoding="utf-8")
            raise SystemExit(1)
        return
    if not args.execute_campus or not args.sdk_python or not args.sdk_python.is_file():
        raise ValueError("ab_probe_explicit_execution_and_sdk_required")
    output = ROOT/"data/test-tmp"/AUTHORIZATION
    output.mkdir(parents=True,exist_ok=False)  # 同一授权只能建立一次，不覆盖/重试。
    source = source_snapshot(output)
    head = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT).decode().strip()
    code = "import sys;sys.path.insert(0,"+repr(str(source/"src"))+");from longmemory.methods.hy_memory.assembly import management_primitives_identity;print(management_primitives_identity())"
    rpc = subprocess.check_output([sys.executable,"-I","-X","utf8","-B","-c",code],cwd=ROOT).decode().strip()
    write_new(output/"source-identity.json",{"native_source_commit":BASE,"native_src_tree":subprocess.check_output(
        ["git","rev-parse",BASE+":src"],cwd=ROOT).decode().strip(),"harness_commit":head,"initial_clean":True,"rpc_source_sha256":rpc})
    gate = HardGate(output/"gate.sqlite3",create=True)
    home = output/"home"
    home.mkdir()
    env = {key:value for key,value in os.environ.items() if key.upper() in {"PATH","SYSTEMROOT","WINDIR","COMSPEC","PATHEXT","SYSTEMDRIVE"}}
    env.update(HOME=str(home),USERPROFILE=str(home),TEMP=str(home),TMP=str(home),CUDA_VISIBLE_DEVICES="",
        HF_HOME=str(home/"hf"),XDG_CACHE_HOME=str(home/"cache"),HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",
        PYTHONIOENCODING="utf-8",PYTHON_DOTENV_DISABLED="1",TOKENIZERS_PARALLELISM="false",
        OMP_NUM_THREADS="2",OPENBLAS_NUM_THREADS="2",MKL_NUM_THREADS="2",NUMEXPR_NUM_THREADS="2")
    spec = importlib.util.spec_from_file_location("ab_owned_job",ROOT/"scripts/development/launcher/winjob.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = module.Job()
    process = subprocess.Popen([sys.executable,"-I","-X","utf8","-B",str(Path(__file__).resolve()),"--worker"],
        cwd=output,env=env,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    started = monotonic()
    reason = None
    lifecycle = Lock()
    timed_out = Event()
    def deadline_stop():
        timed_out.set()
        with lifecycle:
            if job.handle:
                job.api.TerminateJobObject(job.handle,1)
    watchdog = Timer(max(0,gate.snapshot()["deadline_unix"]-time()),deadline_stop)
    watchdog.daemon=True
    try:
        job.assign(process)
        watchdog.start()
        config = {"owner":str(OWNER),"output":str(output),"source":str(source),"sdk_python":str(args.sdk_python.resolve()),"harness_commit":head}
        process.stdin.write((json.dumps(config)+"\n").encode())
        process.stdin.flush()
        process.stdin.close()
        while process.poll() is None:
            state = gate.snapshot()
            if time()>=state["deadline_unix"]:
                reason="wall_deadline"
                gate.halt(reason)
                break
            if state["halted"]:
                reason=state["reason_code"]
                break
            sleep(.05)
    finally:
        watchdog.cancel()
        with lifecycle:
            job.close()
        process.wait(timeout=5)
    if timed_out.is_set():
        reason="wall_deadline"
        gate.halt(reason)
    summary = {"authorization":AUTHORIZATION,"harness_commit":head,"source_commit":BASE,
        "rpc_source_sha256":rpc,
        "wall_seconds":round(monotonic()-started,3),"forced_stop_reason":reason,"exit_code":process.returncode,
        "gate":gate.snapshot(),"receipt_present":(output/"receipt.json").is_file(),"owned_job_closed":True}
    if (output/"free-campus.sqlite3").is_file():
        summary["free_calls"] = calls_snapshot(output/"free-campus.sqlite3")
    if (output/"engine/semantic.sqlite3").is_file():
        with sqlite3.connect((output/"engine/semantic.sqlite3").as_uri()+"?mode=ro",uri=True) as db:
            summary["tasks_after_exit"]=[{"task_id":row[0],"stored_state":row[1],"effective_state":"uncertain" if row[1]=="running" else row[1]}
                for row in db.execute("SELECT id,state FROM tasks")]
    write_new(output/"summary.json",summary)
    print(json.dumps({key:summary[key] for key in ("authorization","wall_seconds","forced_stop_reason","exit_code","receipt_present","owned_job_closed")},ensure_ascii=False))


if __name__=="__main__":
    main()
