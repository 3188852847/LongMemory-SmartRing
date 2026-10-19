"""真实合成验证入口：固定全轮10元账本、已选官方模型、本地BGE、隔离旧日用对照。"""

import argparse
from dataclasses import asdict, replace
from datetime import UTC,datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from time import time
from uuid import uuid4

from longmemory.adapters.llm.candidate_extractor import PROMPT_SHA256, PROMPT_VERSION
from longmemory.adapters.llm.local_embedding import LocalBGEEncoder,REVISION
from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator,SYSTEM_PROMPT
from longmemory.evaluation.runner import provenance
from longmemory.methods.hy_memory.assembly import assemble_hy_backend
from longmemory.methods.hy_memory.budget import PricePolicy,SharedBudget
from longmemory.methods.hy_memory.model_gateway import ModelGateway,selected_model,verify_cny_account
from longmemory.methods.hy_memory.settings import Endpoint,HySettings
from .dataset import load_dataset
from .hy_memory_runner import run_hy_comparison
from .hy_real_baseline import DailyBGEReplay

ROOT=Path(__file__).resolve().parents[4]
MAIN=ROOT.parents[2] if ROOT.parent.name=="worktrees" else ROOT
SDK=ROOT/"local/runtime/hy-memory/.venv/Scripts/python.exe"
CAMPAIGN=ROOT/"local/runtime/hy-memory/real-validation-20261019"


def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")


def sqlite_record_hashes(path):
    if not path.is_file():return {}
    connection=sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)
    try:
        result={}
        available={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("embeddings","embedding_metadata","collections","segments"):
            if table in available:
                rows=connection.execute('SELECT * FROM "'+table+'"').fetchall()
                encoded=json.dumps(sorted((repr(row) for row in rows)),ensure_ascii=False)
                result[table]={"count":len(rows),"sha256":hashlib.sha256(encoded.encode()).hexdigest()}
        return result
    finally:connection.close()


def sdk_view(method,settings):
    memories=[];offset=0
    while True:
        result=method.engine.sdk_call("list_memories",user_id=settings.user_id,agent_id=settings.agent_id,limit=100,offset=offset)
        page=result["vdb"];memories.extend(page["memories"])
        offset+=len(page["memories"])
        if offset>=page["total"]:break
        if not page["memories"]:raise ValueError("sdk_inventory_incomplete")
    profile=method.engine._client.get_user_profile(user_id=settings.user_id).get("profile")
    # 只保存SDK公开视图；没有把未公开RAW/SHADOW推断成不存在。
    profile=None if profile is None else {key:value for key,value in profile.items() if key not in {"request_id","elapsed_ms"}}
    return {"active_memories":sorted(memories,key=lambda row:row["memory_id"]),"profile":profile}


class AuditedMethod:
    def __init__(self,method,directory,settings,*,create_engine,create_sources):
        self.method,self.directory,self.settings=method,directory,settings
        self.new=create_engine;self.query_clone=not create_engine and create_sources
        self.observed=[];self.closed=False
        self.before=sdk_view(method,settings)
        write_json(directory/"inventory-open.json",self.before)

    def __getattr__(self,name):return getattr(self.method,name)
    def observe(self,event):
        result=self.method.observe(event);self.observed.append((event,result));return result
    def close(self):
        if self.closed:return
        audit={}
        try:
            if self.new:
                completed=next(((event,result) for event,result in self.observed if event.role=="user" and result.processing_status=="completed"),None)
                if completed:
                    event,result=completed
                    before=sdk_view(self.method,self.settings)
                    replay=self.method.observe(event)
                    audit["completed_event_replay_same_result"]=asdict(replay)==asdict(result)
                    audit["replay_active_view_unchanged"]=sdk_view(self.method,self.settings)==before
            after=sdk_view(self.method,self.settings)
            write_json(self.directory/"inventory-close.json",after)
            audit["active_view_unchanged_during_lifecycle"]=self.before==after
            audit["source_statuses"]=[self.method.source_status(event.event_id) for event in self.method.journal.events()]
            audit["complete_semantic_freeze_proven"]=False
            write_json(self.directory/"operational-audit.json",audit)
        finally:
            self.method.close();self.closed=True
            write_json(self.directory/"closed-vector-records.json",sqlite_record_hashes(self.directory/"engine/sdk/vector/chroma.sqlite3"))


def load_encoder():
    os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_HUB_DISABLE_TELEMETRY="1",TOKENIZERS_PARALLELISM="false")
    encoder=LocalBGEEncoder(MAIN/"local/runtime/models/bge-small-zh-v1.5"/REVISION)
    encoder._torch.set_num_threads(2)
    vector=encoder.encode_documents(["合成向量验收"])[0]
    if len(vector)!=512 or abs(sum(value*value for value in vector)-1)>0.0001:
        raise ValueError("bge_real_dimension_or_normalization_failed")
    return encoder


def campaign_budget(model):
    path=CAMPAIGN/"budget.db"
    if path.is_file():return SharedBudget(path)
    return SharedBudget(path,policy=PricePolicy(model=model,expires_at_unix=time()+7200),create=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split",choices=("dev","holdout"),default="dev")
    parser.add_argument("--dev-campaign",type=Path)
    parser.add_argument("--probe-only",action="store_true")
    args=parser.parse_args(argv)
    if not SDK.is_file():raise FileNotFoundError("owner_installed_sdk_required")
    model,model_identity=selected_model(MAIN)
    billing=verify_cny_account(model)
    budget=campaign_budget(model.model)
    encoder=load_encoder()
    condition={"source_sha256":provenance()["source_sha256"],"selected_model":model_identity,
        "embedding":encoder.metadata,"embedding_identity":encoder.identity,"embedding_dimensions":512,
        "hy_mode":"pro/chat/legacy/graph-off/profile-on", "hy_query_prefix":"search RPC only; add-internal reconcile embeddings use document policy",
        "baseline":"DailyLLMMemory plus HybridMemoryRetriever and native natural-command/temporal paths",
        "answer_prompt_sha256":hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "baseline_extraction_prompt_sha256":PROMPT_SHA256,"baseline_extraction_prompt_version":PROMPT_VERSION,
        "context_chars":4000,"answer_max_tokens":model.max_tokens,"thinking":"disabled_for_all_conditions",
        "price_policy_sha256":budget.report()["price_policy_sha256"]}
    if args.split=="holdout":
        if args.dev_campaign is None:raise ValueError("holdout_requires_frozen_dev_campaign")
        previous=args.dev_campaign.resolve()
        if not previous.is_relative_to((ROOT/"experiments/runs").resolve()):raise ValueError("dev_campaign_outside_synthetic_runs")
        frozen=json.loads((previous/"frozen-condition.json").read_text(encoding="utf-8"))
        if frozen!=condition:raise ValueError("holdout_condition_changed")
    run=ROOT/"experiments/runs"/("vreal-"+uuid4().hex[:10]);run.mkdir(parents=True,exist_ok=False)
    write_json(run/"condition.json",condition)
    write_json(run/"billing-check.json",billing)
    print(json.dumps({"run":str(run),"stage":"starting","budget":budget.report()["held_or_settled_upper_micro_cny"]},ensure_ascii=False),flush=True)
    with ModelGateway(settings=model,budget=budget,encoder=encoder,currency_verified=True) as gateway:
        provider_identity=hashlib.sha256(json.dumps({"model":model_identity,"embedding":encoder.identity},sort_keys=True).encode()).hexdigest()
        llm=Endpoint(gateway.base+"/hy/v1",model.model,gateway.token,True)
        embedding=Endpoint(gateway.base+"/hy/v1",encoder.identity,gateway.token,True)
        hy=HySettings(user_id="v-real-synthetic-"+args.split,llm=llm,embedding=embedding,
            embedding_dimensions=512,network_authorized=True,max_external_requests=10000,
            managed_gateway=True,provider_identity=provider_identity,include_profile=True,timeout_seconds=120,max_output_tokens=2048)
        answer=lambda:OpenAICompatibleAnswerGenerator(gateway.local_settings("answer",max_tokens=model.max_tokens))
        if budget.report()["attempt_count"]==0 or args.probe_only:
            probe=OpenAICompatibleAnswerGenerator(gateway.local_settings("probe",max_tokens=64)).generate(query="合成连接检查，请只回复：连接正常",memory_context="")
            write_json(run/"probe.json",{"answer":probe,"responses":gateway.responses})
            print(json.dumps({"stage":"paid_probe_complete","budget":budget.report()["held_or_settled_upper_micro_cny"]}),flush=True)
        if not args.probe_only:
            def hy_opener(directory,*,create_engine,create_sources):
                assembly=assemble_hy_backend(settings=hy,state_directory=directory/"engine",source_path=directory/"sources.db",
                    create=create_engine,create_sources=create_sources,python=SDK)
                try:
                    wrapped=AuditedMethod(assembly.method,directory,hy,create_engine=create_engine,create_sources=create_sources)
                    return replace(assembly,method=wrapped)
                except BaseException:assembly.method.close();raise
            baseline=lambda directory,create:DailyBGEReplay(directory,create=create,settings=gateway.local_settings("baseline",max_tokens=1024),encoder=encoder)
            dataset=load_dataset(ROOT/f"datasets/synthetic/hy_memory_{args.split}_v1.json")
            path,report=run_hy_comparison(dataset,output_root=run,hy_opener=hy_opener,baseline_opener=baseline,
                baseline_name="longmemory_daily_llm_bge",generator_factory=answer,split=args.split,
                model_metadata={"provider":"deepseek_official","model":model.model,"endpoint_sha256":model_identity["endpoint_sha256"],"simulated":False},
                hy_metadata={"settings":hy.public(),"dependency_lock_sha256":hashlib.sha256((SDK.parents[2]/"requirements.lock").read_bytes()).hexdigest()})
            write_json(run/"result-pointer.json",{"report":str(path/"report.json"),"status":report["status"],"summary":report["summary"]})
            print(json.dumps({"stage":"comparison_complete","report":str(path/"report.json"),"status":report["status"],"summary":report["summary"]},ensure_ascii=False),flush=True)
        write_json(run/"gateway-observations.json",{"responses":gateway.responses,"embedding_calls":gateway.embedding_calls,"embedding_inputs":gateway.embedding_inputs})
    write_json(run/"budget-after.json",budget.report())
    print(json.dumps({"stage":"closed","run":str(run),"budget_upper_micro_cny":budget.report()["held_or_settled_upper_micro_cny"]},ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
