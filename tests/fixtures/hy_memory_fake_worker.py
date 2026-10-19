"""持久化协议替身，非 Hy SDK/提取算法；仅供合成离线接线测试。"""

import json
from pathlib import Path
import sys


class PersistentFakeClient:
    def __init__(self, workspace, *, create):
        self.file = Path(workspace) / "sdk/fake.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.fail_after = False
        if create:
            with self.file.open("x", encoding="utf-8") as stream:
                json.dump({"rows":[], "adds":0, "searches":0}, stream)
        self.data = json.loads(self.file.read_text(encoding="utf-8"))

    def save(self):
        self.file.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def add(self, data, **kwargs):
        print("fixture stdout noise must not corrupt JSONL")
        eid = kwargs["request_id"]
        self.data["adds"] += 1
        self.data["rows"].append({"memory_id":"item-" + eid, "content":data[0]["content"],
            "layer":"l2_fact", "status":"active", "user_id":kwargs["user_id"],
            "agent_id":kwargs["agent_id"], "meta":[kwargs["meta"]], "score":0.5})
        self.save()
        if self.fail_after:
            raise RuntimeError("synthetic secret exception should not escape")
        return {"success":True, "memory_id":"raw-" + eid, "request_id":eid, "memory_ids":["item-" + eid]}

    def search(self, query, **kwargs):
        self.data["searches"] += 1
        self.save()
        return {"request_id":"fake-search", "memories":{"normal":self.data["rows"][:kwargs["limit"]],
                "schema":[], "proactive":[]}}

    def get_user_profile(self, **kwargs):
        return {"profile":None}

    def list_memories(self, **kwargs):
        rows = list(reversed(self.data["rows"]))
        return {"vdb":{"memories":rows[kwargs["offset"]:kwargs["offset"]+kwargs["limit"]],
                       "total":len(rows)}}

    def get(self, memory_id):
        return next((row for row in self.data["rows"] if row["memory_id"] == memory_id), None)

    def diagnostics(self):
        return {"simulated":True, "external_http_attempts":None, "cost":None}

    def close(self):
        self.save()


def start():
    from longmemory.methods.hy_memory.worker import ProtocolService, RequestBudget, main
    def factory(settings, workspace, *, create):
        return PersistentFakeClient(workspace, create=create), RequestBudget(settings)
    main(service=ProtocolService(factory))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    start()
