"""SDK 外的保守来源依赖门；不修改原生正文、meta 或私有 writer。

原生 meta 是写入事件，不是模型陈述的完整语义来源。派生记录保存整个同范围
持久上下文的潜在依赖包络（不是声称模型实际引用它们）。纠错前先持久隔离；
未观测的旧概括无法还原依赖，管理后须保持未证实隔离。原话逐字匹配不做语义猜测。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from time import perf_counter

from .sdk_bridge import SOURCE_NAMESPACE, _sources


INFERENCE_PREFIX = "[模型提取／概括；不是用户原话，语义来源尚未证实完整]\n"
PROFILE_INFERENCE_PREFIX = "[当前画像由模型提取／聚合；语义来源尚未证实完整]\n"
INTENTION_INFERENCE_PREFIX = "[未来意图由模型提取；语义来源尚未证实完整]\n"
DERIVED = {"l0_basic_info", "l2_fact", "l3_summary", "l4_identity", "l7_intention"}
AUDIT = {"get", "list_memories", "history", "update", "delete", "layer_page", "layer_detail"}
LIMIT = 10000


@dataclass(frozen=True)
class LedgerSnapshot:
    records: dict
    retired: frozenset
    legacy_barrier: bool
    corrections: dict
    ledger_queries: int
    audit_queries: int
    audit_connections: int


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


class ProvenanceGuard:
    def __init__(self, client, settings, budget, workspace):
        self.client, self.settings, self.budget = client, settings, budget
        self.path = workspace / "provenance.sqlite3"
        self.audit = workspace / "management.sqlite3"
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError("hy_provenance_ledger_link_denied")
        self.capture = ContextVar("hy_provenance_capture", default=None)
        self._last_capture = None
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, hash TEXT NOT NULL, kind TEXT NOT NULL, dependencies TEXT NOT NULL, invalid INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS retired (source TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY,value INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO control VALUES ('legacy_barrier',0)")
        store = client._vector_store
        self.get = store.get_by_id
        self.list = store.list_by_user
        self.search = store.search
        self.upsert = store.upsert
        self.upsert_batch = store.upsert_batch
        # 仅包装这个owner的存储实例；管理/审计仍可读取被隔离记录。
        async def get(node_id):
            node = await self.get(node_id)
            return node if self.budget.operation in AUDIT or await self.allowed(node) else None
        async def list(*args, **kwargs):
            nodes = await self.list(*args, **kwargs)
            return nodes if self.budget.operation in AUDIT else [n for n in nodes if await self.allowed(n)]
        async def search(*args, **kwargs):
            hits = await self.search(*args, **kwargs)
            return hits if self.budget.operation in AUDIT else [h for h in hits if await self.allowed(h.get("node"))]
        async def upsert(node):
            self.before_write(node)
            return await self.upsert(node)
        async def upsert_batch(nodes):
            for node in nodes:
                self.before_write(node)
            return await self.upsert_batch(nodes)
        store.get_by_id, store.list_by_user, store.search = get, list, search
        store.upsert, store.upsert_batch = upsert, upsert_batch

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def owned(self, node):
        if node is None or node.user_id != self.settings.user_id:
            return False
        if node.layer.value == "l0_basic_info":
            return node.agent_id in {None, "", self.settings.agent_id} and node.source in {"default", SOURCE_NAMESPACE}
        return node.agent_id == self.settings.agent_id and node.source == SOURCE_NAMESPACE

    def sources(self, node):
        return _sources((node.custom or {}).get("meta")) or ()

    def record(self, node):
        with self.db() as db:
            row = db.execute("SELECT hash,kind,dependencies,invalid FROM records WHERE id=?", (node.node_id,)).fetchone()
        return row if row and row[0] == digest(node.content) else None

    def correction_source(self, node):
        # 平台已独立读回且completed后才承认新来源；running/uncertain不进入提取。
        if not self.audit.is_file() or self.audit.is_symlink() or self.audit.is_junction():
            return None
        db = sqlite3.connect(self.audit.as_uri()+"?mode=ro", uri=True, timeout=2)
        try:
            rows = db.execute("SELECT source_event_id,state,action FROM operations WHERE item_id=? ORDER BY rowid DESC LIMIT 1", (node.node_id,)).fetchall()
            return rows[0][0] if len(rows) == 1 and rows[0][1:] == ("completed", "correct") else None
        finally:
            db.close()

    def management_pending(self):
        if not self.audit.is_file():
            return False
        db = sqlite3.connect(self.audit.as_uri()+"?mode=ro",uri=True,timeout=2)
        try:
            return db.execute("SELECT 1 FROM operations WHERE state='running' LIMIT 1").fetchone() is not None
        finally:
            db.close()

    async def literal(self, node):
        """完整原话相等才证明逐字引用；不使用子串、关键词或模型自评。"""
        if not self.owned(node) or node.layer.value not in {"l2_fact", "l3_summary", "l7_intention"}:
            return False
        custom = node.custom or {}
        refs = set(custom.get("source_raw_memory_ids") or [])
        if node.source_raw_memory_id:
            refs.add(node.source_raw_memory_id)
        if len(refs) != 1 or not self.sources(node):
            return False
        raw = await self.get(next(iter(refs)))
        return bool(self.owned(raw) and raw.layer.value == "l1_raw" and self.sources(raw) == self.sources(node)
            and all(m.get("role") == "user" for m in (raw.custom or {}).get("meta") or [])
            and raw.content in {node.content, "[user]: "+node.content})

    def _literal_from(self, node, nodes):
        if not self.owned(node) or node.layer.value not in {"l2_fact","l3_summary","l7_intention"}:
            return False
        refs=set((node.custom or {}).get("source_raw_memory_ids") or [])
        if node.source_raw_memory_id:
            refs.add(node.source_raw_memory_id)
        if len(refs)!=1 or not self.sources(node):
            return False
        raw=nodes.get(next(iter(refs)))
        return bool(self.owned(raw) and raw.layer.value=="l1_raw" and self.sources(raw)==self.sources(node)
            and all(m.get("role")=="user" for m in (raw.custom or {}).get("meta") or [])
            and raw.content in {node.content,"[user]: "+node.content})

    def ledger_snapshot(self, nodes):
        """同一个SQLite读事务，按参数块读取；不逐节点connect、不读取正文。"""
        if len(nodes)>LIMIT or any(not self.owned(node) for node in nodes):
            raise ValueError("hy_provenance_context_envelope_unproven")
        identifiers=list(dict.fromkeys(node.node_id for node in nodes))
        sources=list({s for node in nodes for s in self.sources(node)})
        records,retired={},set()
        queries,audit_queries,audit_connections=0,0,0
        def chunks(values):
            for index in range(0,len(values),900):
                yield values[index:index+900]
        with self.db() as db:
            db.execute("BEGIN")
            barrier=bool(db.execute("SELECT value FROM control WHERE key='legacy_barrier'").fetchone()[0])
            queries+=1
            for batch in chunks(identifiers):
                # 接纳只需hash/kind/invalid；历史依赖JSON仅在管理失效阶段读取，
                # 避免每次add重新装入所有旧祖先包络。tuple位置保持私有读取形状。
                rows=db.execute("SELECT id,hash,kind,NULL,invalid FROM records WHERE id IN ("+",".join("?" for _ in batch)+")",batch)
                records.update((row[0],row[1:]) for row in rows)
                queries+=1
            for batch in chunks(sources):
                retired.update(row[0] for row in db.execute("SELECT source FROM retired WHERE source IN ("+",".join("?" for _ in batch)+")",batch))
                queries+=1
        correction_ids=[node.node_id for node in nodes if (row:=records.get(node.node_id)) and row[0]==digest(node.content) and row[1]=="correction"]
        corrections={}
        if correction_ids and self.audit.is_file() and not self.audit.is_symlink() and not self.audit.is_junction():
            db=sqlite3.connect(self.audit.as_uri()+"?mode=ro",uri=True,timeout=2)
            audit_connections=1
            try:
                db.execute("BEGIN")
                for batch in chunks(correction_ids):
                    rows=db.execute("SELECT item_id,source_event_id,state,action FROM operations WHERE item_id IN ("+",".join("?" for _ in batch)+") ORDER BY rowid DESC LIMIT 10001",batch).fetchall()
                    audit_queries+=1
                    if len(rows)>LIMIT:
                        raise ValueError("hy_provenance_audit_envelope_unproven")
                    latest={}
                    for identifier,source,state,action in rows:
                        latest.setdefault(identifier,(source,state,action))
                    corrections.update((identifier,row[0]) for identifier,row in latest.items() if row[1:]==("completed","correct"))
            finally:
                db.close()
        return LedgerSnapshot(records,frozenset(retired),barrier,corrections,queries,audit_queries,audit_connections)

    def _snapshot_record(self,node,snapshot):
        row=snapshot.records.get(node.node_id)
        return row if row and row[0]==digest(node.content) else None

    def allowed_from(self,node,snapshot,nodes):
        if not self.owned(node):
            return False
        row=self._snapshot_record(node,snapshot)
        if row and row[1]=="correction":
            return not row[3] and node.node_id in snapshot.corrections
        if set(self.sources(node)) & snapshot.retired or row and row[3]:
            return False
        if node.layer.value not in DERIVED:
            return True
        if row:
            return row[1]!="unknown" or not snapshot.legacy_barrier
        return not snapshot.legacy_barrier or self._literal_from(node,nodes)

    async def allowed(self, node):
        if node is None:
            return False
        # 此适配器不替其他namespace/用户作来源断言；固定owner管线拒绝跨范围材料。
        if not self.owned(node):
            return False
        row = self.record(node)
        if row and row[1] == "correction":
            return not row[3] and self.correction_source(node) is not None
        sources = self.sources(node)
        with self.db() as db:
            retired = (db.execute("SELECT 1 FROM retired WHERE source IN ("+",".join("?" for _ in sources)+") LIMIT 1",sources).fetchone()
                if sources else None)
            barrier = db.execute("SELECT value FROM control WHERE key='legacy_barrier'").fetchone()[0]
        if retired or row and row[3]:
            return False
        if node.layer.value not in DERIVED:
            return True
        if row:
            return row[1] != "unknown" or not barrier
        return not barrier or await self.literal(node)

    async def begin_add(self, arguments):
        # 包络包括L0及原始历史；不声称它们都被模型引用。超界拒绝本次写入，
        # 不能截断后伪装成可安全失效的依赖集。不会扫描/写个人库。
        started=perf_counter()
        nodes = await self.list(user_id=self.settings.user_id, limit=LIMIT+1, with_vectors=False, allow_raw_layer=True)
        listed=perf_counter()
        if len(nodes) > LIMIT or any(not self.owned(n) for n in nodes):
            raise ValueError("hy_provenance_context_envelope_unproven")
        snapshot=self.ledger_snapshot(nodes)
        loaded=perf_counter()
        by_id={node.node_id:node for node in nodes}
        dependencies = {"source:"+arguments["request_id"]}
        for node in nodes:
            if not self.allowed_from(node,snapshot,by_id):
                continue
            dependencies.add("node:"+node.node_id)
            row = self._snapshot_record(node,snapshot)
            sources = (snapshot.corrections.get(node.node_id),) if row and row[1] == "correction" else self.sources(node)
            dependencies.update("source:"+s for s in sources if s)
            # 传递关系由持久节点边保留，不把每个祖先包络复制到每个新记录。
            # 未观测旧概括额外依赖保守屏障，任何管理都使这条潜在链失效。
            if not row and node.layer.value in DERIVED and not self._literal_from(node,by_id):
                dependencies.add("legacy:unverified")
        data = arguments.get("data") or []
        literal = data[0]["content"] if len(data) == 1 and data[0].get("role") == "user" else None
        result=sorted(dependencies), literal, arguments["request_id"]
        self._last_capture={"node_count":len(nodes),"list_ms":(listed-started)*1000,
            "ledger_ms":(loaded-listed)*1000,"projection_ms":(perf_counter()-loaded)*1000,
            "elapsed_ms":(perf_counter()-started)*1000,"ledger_connections":1,
            "audit_connections":snapshot.audit_connections,"ledger_queries":snapshot.ledger_queries,
            "audit_queries":snapshot.audit_queries,"node_limit":LIMIT}
        return result

    def diagnostics(self):
        return dict(self._last_capture) if self._last_capture is not None else None

    def end_add(self, token):
        self.capture.reset(token)

    def before_write(self, node):
        if not self.owned(node) or node.layer.value not in DERIVED or self.budget.operation in {"update", "delete"}:
            return
        state = self.capture.get()
        # 只捕获add；S2的归档/强度维护不能复活既有失效标记。
        if state is None:
            return
        dependencies, literal, event_id = state
        kind = "verbatim_user" if (node.layer.value in {"l2_fact", "l3_summary", "l7_intention"} and literal is not None
            and node.content == literal and self.sources(node) == (event_id,)) else "context_inference"
        if kind == "verbatim_user":
            dependencies = ["source:"+event_id]
        with self.db() as db:
            old = db.execute("SELECT invalid FROM records WHERE id=?", (node.node_id,)).fetchone()
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)", (node.node_id, digest(node.content), kind,
                json.dumps(dependencies), old[0] if old else 0))

    def invalidate(self, row, operation, content=None):
        """写SDK前提交墓碑；SDK失败也不解除隔离，不回放或批量改写原生库。"""
        sources = set(_sources(row.get("meta")) or ())
        with self.db() as db:
            db.execute("UPDATE control SET value=1 WHERE key='legacy_barrier'")
            db.executemany("INSERT OR IGNORE INTO retired VALUES (?)", ((s,) for s in sources))
            invalid = {"legacy:unverified", "node:"+row["memory_id"], *("source:"+s for s in sources)}
            records = db.execute("SELECT id,dependencies FROM records").fetchall()
            changed = True
            while changed:
                changed = False
                for identifier, dependencies in records:
                    key = "node:"+identifier
                    if key not in invalid and set(json.loads(dependencies)) & invalid:
                        invalid.add(key)
                        changed = True
            db.executemany("UPDATE records SET invalid=1 WHERE id=?", ((k[5:],) for k in invalid if k.startswith("node:")))
            if operation == "update":
                db.execute("INSERT OR REPLACE INTO records VALUES (?,?, 'correction','[]',0)", (row["memory_id"], digest(content)))

    async def project(self, node, content):
        row = self.record(node)
        literal = row and row[1] in {"verbatim_user", "correction"} or await self.literal(node)
        return content if literal or content.startswith(INFERENCE_PREFIX) else INFERENCE_PREFIX+content

    async def describe(self, node):
        row = self.record(node)
        literal = bool(row and row[1] == "verbatim_user" or await self.literal(node))
        correction = bool(row and row[1] == "correction" and self.correction_source(node))
        return {"status":"explicit_correction" if correction else "verbatim_user" if literal else "model_inference_unverified",
            "semantic_source_complete":literal or correction,
            "dependency_basis":"explicit_correction" if correction else "verbatim_current_input" if row and row[1]=="verbatim_user"
                else "raw_exact_match" if literal else "scope_context_envelope" if row else "legacy_unobserved",
            "injection_allowed":await self.allowed(node)}

    async def project_schema(self, evidence_ids, content):
        if not evidence_ids:
            prefix="[模型归纳缺少可核验支撑；语义来源尚未证实完整]\n"
            return content if content.startswith(prefix) else prefix+content
        for identifier in evidence_ids:
            node = await self.get(identifier)
            if node is None or not (await self.describe(node))["semantic_source_complete"]:
                prefix = "[部分支撑是模型概括；语义来源尚未证实完整]\n"
                return content if content.startswith(prefix) else prefix+content
        return content

    async def project_intention(self,node,content):
        complete=(await self.describe(node))["semantic_source_complete"]
        return content if complete or content.startswith(INTENTION_INFERENCE_PREFIX) else INTENTION_INFERENCE_PREFIX+content

    def profile_description(self,nodes):
        snapshot=self.ledger_snapshot(nodes)
        by_id={node.node_id:node for node in nodes}
        return {"status":"model_inference_unverified","semantic_source_complete":False,
            "dependency_basis":"scope_context_envelope" if all(self._snapshot_record(n,snapshot) for n in nodes) else "legacy_unobserved",
            "injection_allowed":all(self.allowed_from(n,snapshot,by_id) for n in nodes)}

    async def project_search(self, response):
        rows = []
        for row in response["memories"]["normal"]:
            ids = [row["memory_id"], *(v["node_id"] for v in row.get("evolution_chain") or [])]
            nodes = [await self.get(i) for i in ids]
            if not all([await self.allowed(n) for n in nodes]):
                continue
            # 可见版本中任一概括都必须保留推断标记。
            content = row["content"]
            for node in nodes:
                content = await self.project(node, content)
            row["content"] = content
            rows.append(row)
        response["memories"]["normal"] = rows
        return response
