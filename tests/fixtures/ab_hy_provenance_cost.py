"""固定旧来源门与批量门的纯本地同规模成本对照；不导入SDK/模型/网络。"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import median
import subprocess
import sys
from time import perf_counter
from types import ModuleType,SimpleNamespace


ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
BASELINE="92d40492"


class Store:
    def __init__(self,nodes):self.nodes=nodes
    async def get_by_id(self,identifier):return None
    async def list_by_user(self,**kwargs):
        assert kwargs["limit"]==10001 and kwargs["allow_raw_layer"] is True
        return self.nodes
    async def search(self,**kwargs):return []
    async def upsert(self,node):return node.node_id
    async def upsert_batch(self,nodes):return [node.node_id for node in nodes]


def run(output):
    from longmemory.methods.hy_memory import provenance as current_module
    from longmemory.methods.hy_memory.provenance import ProvenanceGuard
    from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT/"data/test-tmp"):
        raise ValueError("ab_cost_requires_owned_test_directory")
    output.mkdir(parents=True,exist_ok=False)
    payload=subprocess.check_output(["git","show",BASELINE+":src/longmemory/methods/hy_memory/provenance.py"],cwd=ROOT)
    (output/"baseline_provenance.py").write_bytes(payload)
    module=ModuleType("longmemory.methods.hy_memory._ab_cost_baseline")
    module.__package__="longmemory.methods.hy_memory"
    exec(compile(payload,str(output/"baseline_provenance.py"),"exec"),module.__dict__)
    settings=SimpleNamespace(user_id="ab-cost",agent_id="ab-cost-agent")
    result={"baseline_commit":BASELINE,"baseline_blob_sha256":hashlib.sha256(payload).hexdigest(),
        "batched_guard_sha256":hashlib.sha256(Path(current_module.__file__).read_bytes()).hexdigest(),
        "scope":"guard.begin_add only; synthetic untracked L2; same SSD/worktree/interpreter; no SDK/vector store/model load",
        "repetitions":3,"new_school_calls":0,"sdk_imported":False,"cases":[]}
    for size in (1000,10000):
        nodes=[SimpleNamespace(node_id=f"ab-cost-{i}",content=f"合成记录{i}",user_id=settings.user_id,agent_id=settings.agent_id,
            source=SOURCE_NAMESPACE,layer=SimpleNamespace(value="l2_fact"),source_raw_memory_id=None,
            custom={"meta":[{"namespace":SOURCE_NAMESPACE,"role":"user","source_event_ids":[f"ab-cost-source-{i}"]}]}) for i in range(size)]
        samples={"baseline":[],"batched":[]}
        for repetition in range(3):
            dependencies={}
            for name,guard_type in (("baseline",module.ProvenanceGuard),("batched",ProvenanceGuard)):
                directory=output/f"{size}-{repetition}-{name}"
                directory.mkdir()
                guard=guard_type(SimpleNamespace(_vector_store=Store(nodes)),settings,SimpleNamespace(operation=None),directory)
                original=sqlite3.connect
                connections=[]
                def counted(*args,**kwargs):
                    connections.append(True)
                    return original(*args,**kwargs)
                sqlite3.connect=counted
                try:
                    started=perf_counter()
                    capture=asyncio.run(guard.begin_add({"request_id":"next","data":[{"role":"user","content":"下一条合成输入。"}]}))
                    elapsed=(perf_counter()-started)*1000
                finally:
                    sqlite3.connect=original
                dependencies[name]=set(capture[0])
                samples[name].append({"elapsed_ms":round(elapsed,3),"sqlite_connections":len(connections),
                    "dependency_count":len(capture[0]),"stages":guard.diagnostics() if name=="batched" else None})
            assert dependencies["baseline"] <= dependencies["batched"]
            assert dependencies["batched"]-dependencies["baseline"]=={"legacy:unverified"}
        assert all(row["sqlite_connections"]==size*3 for row in samples["baseline"])
        assert all(row["sqlite_connections"]==1 for row in samples["batched"])
        result["cases"].append({"node_count":size,"baseline_median_ms":median(row["elapsed_ms"] for row in samples["baseline"]),
            "batched_median_ms":median(row["elapsed_ms"] for row in samples["batched"]),"samples":samples,
            "old_direct_dependency_set_preserved":True,"additional_conservative_legacy_barrier":True})
    assert not any(name=="hy_memory" or name.startswith("hy_memory.") for name in sys.modules)
    with (output/"summary.json").open("x",encoding="utf-8") as stream:json.dump(result,stream,indent=2)
    print(json.dumps({"cases":[{k:row[k] for k in ("node_count","baseline_median_ms","batched_median_ms")} for row in result["cases"]]}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    run(args.output)
