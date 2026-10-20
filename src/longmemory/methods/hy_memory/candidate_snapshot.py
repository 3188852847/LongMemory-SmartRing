"""候选专用的原生只读快照；不调用正式prepare/search/LLM/embedding。"""

from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
import secrets
from time import time

from .sdk_bridge import SOURCE_NAMESPACE, _sources
from .semantic import graph_evidence, read_intentions, read_profile


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":"))


class CandidateSnapshots:
    OPERATIONS = {"candidate_snapshot", "candidate_validate"}

    def __init__(self, client, settings, budget):
        self.client, self.settings, self.budget = client, settings, budget
        self._key = secrets.token_bytes(32)
        self._revision = 0

    def changed(self):
        self._revision += 1

    def _version(self):
        semantic = getattr(self.budget,"semantic",None)
        if semantic is None:
            return {"revision":self._revision,"epoch":None,"ready_epoch":None,"stable":True}
        with semantic._condition, semantic._db() as db:
            revision = db.execute("SELECT value FROM control WHERE key='revision'").fetchone()[0]
            running = db.execute("SELECT 1 FROM tasks WHERE state='running' LIMIT 1").fetchone()
            return {"revision":revision+self._revision,"epoch":semantic._epoch(db),
                "ready_epoch":db.execute("SELECT value FROM control WHERE key='ready_epoch'").fetchone()[0],
                "stable":not running and not semantic._work.locked()}

    async def _read(self, embedding, limit):
        from hy_memory.models.memory import MemoryLayer, MemoryStatus, MemoryNode
        hits = await self.client._vector_store.search(query_embedding=embedding,
            user_ids=[self.settings.user_id],agent_ids=[self.settings.agent_id],include_sources=[SOURCE_NAMESPACE],
            layers=[MemoryLayer.L2_FACT,MemoryLayer.L3_SUMMARY,MemoryLayer.L4_IDENTITY],
            status_filter=[MemoryStatus.ACTIVE],only_latest=True,limit=limit,score_threshold=0.4)
        items = []
        for hit in hits:
            node = hit.get("node")
            if (node is None or node.user_id!=self.settings.user_id or node.agent_id!=self.settings.agent_id
                    or node.source!=SOURCE_NAMESPACE):
                raise ValueError("hy_candidate_scope_unproven")
            sources = _sources((node.custom or {}).get("meta"))
            items.append({"memory_id":node.node_id,"content":node.content[:32768],"layer":node.layer.value,
                "channel":"normal","source_event_ids":list(sources) if sources else None,"evidence_memory_ids":[node.node_id]})
        if self.settings.include_profile:
            profile = (await read_profile(self.client,self.settings,self.budget))["profile"]
            if profile:
                sources = _sources(profile.get("meta"))
                items.insert(0,{"memory_id":profile["memory_id"],"content":profile["content"],"layer":"l0_basic_info",
                    "channel":"profile","source_event_ids":list(sources) if sources else None,"evidence_memory_ids":[profile["memory_id"]]})
        expiry = time()+30
        if self.settings.semantic_layers_enabled:
            status = self.budget.semantic.gate()
            if status["schema_state"]=="ready":
                graph = self.client._graph_store
                hits = await graph.vector_search(query_embedding=embedding,
                    isolation_key=MemoryNode.build_isolation_key(self.settings.user_id,self.settings.agent_id),
                    layers=["l6_schema"],include_sources=[SOURCE_NAMESPACE],limit=3,score_threshold=0.4)
                for hit in hits:
                    node = await graph.get_node(hit["node_id"])
                    if node is None or node.user_id!=self.settings.user_id or node.agent_id!=self.settings.agent_id or node.source!=SOURCE_NAMESPACE:
                        raise ValueError("hy_candidate_graph_scope_unproven")
                    meta, evidence = await graph_evidence(self.client,self.settings,node)
                    if meta:
                        items.append({"memory_id":node.node_id,"content":node.content[:32768],"layer":"l6_schema","channel":"schema",
                            "source_event_ids":list(_sources(meta)),"evidence_memory_ids":[node.node_id,*evidence]})
            intentions = await read_intentions(self.client,self.settings,embedding)
            for row in intentions:
                node = await self.client._vector_store.get_by_id(row["memory_id"])
                if node is not None and node.valid_until is not None:
                    expiry = min(expiry,node.valid_until.timestamp())
                sources = _sources(row.get("meta"))
                items.append({"memory_id":row["memory_id"],"content":row["content"][:32768],"layer":"l7_intention","channel":"proactive",
                    "source_event_ids":list(sources) if sources else None,"evidence_memory_ids":[row["memory_id"]]})
        return items,expiry

    def snapshot(self, *, query_embedding, limit=5):
        if (not isinstance(query_embedding,list) or len(query_embedding)!=self.settings.embedding_dimensions
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in query_embedding)
                or not any(v!=0 for v in query_embedding) or type(limit) is not int or not 1<=limit<=10):
            raise ValueError("hy_candidate_options_invalid")
        before = self._version()
        if not before["stable"]:
            return {"protocol":1,"read_status":"busy","snapshot_token":None,"items":[],**before}
        items,expiry = self.client._search_loop_thread.run(self._read(query_embedding,limit))
        after = self._version()
        if before!=after or not after["stable"]:
            return {"protocol":1,"read_status":"changed","snapshot_token":None,"items":[],**after}
        digest = hashlib.sha256(_canonical(items).encode()).hexdigest()
        payload = {"revision":after["revision"],"epoch":after["epoch"],"ready_epoch":after["ready_epoch"],
            "expires_at":expiry,"memory_digest":digest}
        encoded = _canonical(payload)
        token = encoded+"."+hmac.new(self._key,encoded.encode(),hashlib.sha256).hexdigest()
        return {"protocol":1,"read_status":"readable","snapshot_token":token,"items":items,**after,
            "expires_at":datetime.fromtimestamp(expiry,UTC).isoformat(),"memory_digest":digest,
            "policy":"latest_only_no_history_expansion_no_models_no_semantic_writes"}

    def validate(self, *, snapshot_token):
        result = {"protocol":1,"valid":False,"reason_code":"invalid_token"}
        if not isinstance(snapshot_token,str) or len(snapshot_token)>2048:
            return result
        try:
            encoded,signature = snapshot_token.rsplit(".",1)
            if not hmac.compare_digest(signature,hmac.new(self._key,encoded.encode(),hashlib.sha256).hexdigest()):
                return result
            payload = json.loads(encoded)
            if payload["expires_at"]<=time():
                return {**result,"reason_code":"expired"}
            version = self._version()
            if not version["stable"] or any(payload[key]!=version[key] for key in ("revision","epoch","ready_epoch")):
                return {**result,"reason_code":"memory_changed_or_busy"}
            return {"protocol":1,"valid":True,"reason_code":None,"memory_digest":payload["memory_digest"],
                "revision":version["revision"],"epoch":version["epoch"]}
        except (ValueError,KeyError,TypeError):
            return result

    def execute(self, operation, arguments):
        if operation=="candidate_snapshot" and isinstance(arguments,dict) and set(arguments)<={"query_embedding","limit"} and "query_embedding" in arguments:
            return self.snapshot(**arguments)
        if operation=="candidate_validate" and isinstance(arguments,dict) and set(arguments)=={"snapshot_token"}:
            return self.validate(**arguments)
        raise ValueError("hy_candidate_arguments_invalid")
