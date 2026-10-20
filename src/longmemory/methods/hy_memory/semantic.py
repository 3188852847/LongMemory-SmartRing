"""固定 SDK 的受控 L6/L7：持久任务、失效门与无副作用召回。

原生 evolve 非幂等；账本只保证相同任务不再次认领，不承诺跨 SDK 事务。
未确认的任务不重放，L6 不注入。L7 永远不是执行授权或已经发生的事实。
"""

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
import hashlib
import json
import sqlite3
from threading import Condition, Lock, Thread
from time import perf_counter

from .sdk_bridge import SOURCE_NAMESPACE, _sources


class SemanticBusy(RuntimeError):
    pass


def invalidate_inactive_semantics(workspace):
    """pro回退写入也使保留图失效；不打开图/模型、不创建任务或空账本。"""
    if workspace is None:
        return
    path = workspace/"semantic.sqlite3"
    if not path.is_file():
        return
    from .management_rpc import owner_lease_held
    if path.is_symlink() or path.is_junction() or not owner_lease_held(workspace):
        raise ValueError("hy_inactive_semantic_owner_unproven")
    db = sqlite3.connect(path.as_uri()+"?mode=rw",uri=True,timeout=2)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            keys = dict(db.execute("SELECT key,value FROM control"))
            if any(type(keys.get(key)) is not int for key in ("epoch","ready_epoch","revision")):
                raise ValueError("hy_inactive_semantic_control_unproven")
            db.execute("UPDATE control SET value=value+1 WHERE key IN ('epoch','revision')")
            db.execute("UPDATE control SET value=-1 WHERE key='ready_epoch'")
    finally:
        db.close()


def task_id(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or any(ord(c) < 32 for c in value)):
        raise ValueError("hy_semantic_task_id_invalid")
    return value


class SemanticCoordinator:
    """一个 SDK owner 内的后台调度；不额外打开 Chroma/Kuzu，不使用原生队列。"""

    OPERATIONS = {"semantic_status", "semantic_enqueue", "semantic_task", "semantic_cancel", "semantic_pause"}

    def __init__(self, client, settings, workspace, *, start=True, background=None):
        self.client, self.settings = client, settings
        self.background = background
        self.path = workspace / "semantic.sqlite3"
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError("hy_semantic_ledger_link_denied")
        self._condition = Condition()
        self._work = Lock()
        self._stopping = False
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL, finished TEXT, elapsed_ms REAL, reason TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_state_created ON tasks(state,created,id)")
            db.execute("CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO control VALUES ('epoch',0)")
            db.execute("INSERT OR IGNORE INTO control VALUES ('ready_epoch',-1)")
            db.execute("INSERT OR IGNORE INTO control VALUES ('paused',0)")
            db.execute("INSERT OR IGNORE INTO control VALUES ('revision',0)")
            # owner 已持有租约；旧 running 没有跨库原子回执，绝不自动重试。
            count = db.execute("UPDATE tasks SET state='uncertain',reason='owner_restart' WHERE state='running'").rowcount
            if count:
                db.execute("UPDATE control SET value=-1 WHERE key='ready_epoch'")
            db.execute("UPDATE tasks SET state='cancelled',reason='restart_requires_explicit_enqueue' WHERE state='pending'")
        self._thread = Thread(target=self._run, name="hy-semantic", daemon=True)
        if start:
            self._thread.start()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _epoch(self, db):
        return db.execute("SELECT value FROM control WHERE key='epoch'").fetchone()[0]

    def dirty(self):
        with self._condition, self._db() as db:
            db.execute("UPDATE control SET value=value+1 WHERE key='epoch'")
            db.execute("UPDATE control SET value=value+1 WHERE key='revision'")
            db.execute("UPDATE control SET value=-1 WHERE key='ready_epoch'")

    def status(self):
        with self._condition, self._db() as db:
            epoch = self._epoch(db)
            ready = db.execute("SELECT value FROM control WHERE key='ready_epoch'").fetchone()[0]
            counts = dict(db.execute("SELECT state,COUNT(*) FROM tasks GROUP BY state"))
            paused = bool(db.execute("SELECT value FROM control WHERE key='paused'").fetchone()[0])
            last = db.execute("SELECT MAX(finished) FROM tasks").fetchone()[0]
            return {"protocol": 2, "enabled": True, "desired_enabled": self.settings.semantic_layers_enabled,
                "mode": "ultra", "task_counts": counts, "paused": paused, "last_task_finished_at": last,
                "graph_available": bool(getattr(getattr(self.client, "_graph_store", None), "_available", False)),
                "management_available": not self._work.locked() and self.settings.management_writes_enabled,
                "schema_state": "ready" if ready == epoch else "isolated",
                "epoch": epoch, "ready_epoch": ready,
                "native_evolve_idempotent": False, "automatic_restart_replay": False,
                "intention_read": "read_only_expiry_filter_and_dedup",
                "expired_intention_policy": "archive_not_assert_completion",
                "execution_authorized": False, "proactive_contact_enabled": False}

    def gate(self):
        """聊天路径只读固定控制行，不随历史任务数量重复聚合统计。"""
        with self._condition, self._db() as db:
            values = dict(db.execute("SELECT key,value FROM control"))
            return {"schema_state":"ready" if values["epoch"]==values["ready_epoch"] else "isolated",
                "paused":bool(values["paused"])}

    def pause(self, paused):
        if type(paused) is not bool:
            raise ValueError("hy_semantic_pause_invalid")
        with self._condition, self._db() as db:
            db.execute("UPDATE control SET value=? WHERE key='paused'", (int(paused),))
            self._condition.notify_all()
        return {"paused": paused, "running_effect": "already_claimed_no_rollback"}

    def task(self, identifier):
        task_id(identifier)
        with self._condition, self._db() as db:
            row = db.execute("SELECT id,kind,state,created,finished,elapsed_ms,reason FROM tasks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LookupError("hy_semantic_task_missing")
        return dict(zip(("task_id", "kind", "state", "created_at", "finished_at", "elapsed_ms", "reason_code"), row))

    def enqueue(self, identifier, *, kind="evolve", max_batches=1):
        task_id(identifier)
        if kind not in {"evolve", "intention_maintenance"} or type(max_batches) is not int or not 1 <= max_batches <= 4:
            raise ValueError("hy_semantic_task_options_invalid")
        payload = json.dumps({"max_batches": max_batches}, sort_keys=True)
        with self._condition, self._db() as db:
            if self._stopping:
                raise RuntimeError("hy_semantic_closing")
            old = db.execute("SELECT kind,payload FROM tasks WHERE id=?", (identifier,)).fetchone()
            if old is not None and old != (kind, payload):
                raise ValueError("hy_semantic_task_payload_conflict")
            if old is None:
                db.execute("INSERT INTO tasks(id,kind,payload,state,created) VALUES (?,?,?,'pending',?)",
                    (identifier, kind, payload, datetime.now(UTC).isoformat()))
            self._condition.notify_all()
        return self.task(identifier)

    def cancel(self, identifier):
        task_id(identifier)
        with self._condition, self._db() as db:
            # 已认领不能安全中断 SDK 多步落库；仅排队任务可取消。
            db.execute("UPDATE tasks SET state='cancelled',reason='cancelled_before_claim' WHERE id=? AND state='pending'", (identifier,))
        result = self.task(identifier)
        result["cancellation_effect"] = "prevented_start" if result["state"] == "cancelled" else "already_claimed_no_rollback"
        return result

    def after_add(self, event_id):
        # 平台仅对成功且未取消的话轮投递 add；不从轮次准备/取消路径写记忆。
        identifier = "add:" + hashlib.sha256(event_id.encode()).hexdigest()
        self.enqueue(identifier+":expiry", kind="intention_maintenance")
        return self.enqueue(identifier)

    def _run(self):
        while True:
            with self._condition:
                if self._stopping:
                    return
                with self._db() as db:
                    paused = db.execute("SELECT value FROM control WHERE key='paused'").fetchone()[0]
                    row = None if paused else db.execute("SELECT id,kind,payload FROM tasks WHERE state='pending' ORDER BY created,id LIMIT 1").fetchone()
                if row is None:
                    self._condition.wait(timeout=0.5)
                    continue
            # 建议不是lease：先查，忙时保持pending且不拿_work，不占running任务。
            # 放行后到原生HTTP之间仍可能有新前台到达，由网关实际队列决定优先级。
            if row[1] == "evolve" and self.background is not None and not self.background.eligible():
                with self._condition:
                    if not self._stopping:
                        self._condition.wait(timeout=0.5)
                continue
            with self._work:
                with self._condition, self._db() as db:
                    if self._stopping:
                        return
                    claimed = db.execute("UPDATE tasks SET state='running' WHERE id=? AND state='pending'", (row[0],)).rowcount
                    if not claimed:
                        continue
                    epoch = self._epoch(db)
                    paused = db.execute("SELECT value FROM control WHERE key='paused'").fetchone()[0]
                    if paused:
                        db.execute("UPDATE tasks SET state='pending' WHERE id=?", (row[0],))
                        continue
                    db.execute("UPDATE control SET value=value+1 WHERE key='revision'")
                    if row[1] == "evolve":
                        db.execute("UPDATE control SET value=-1 WHERE key='ready_epoch'")
                started = perf_counter()
                state, reason = "uncertain", "sdk_outcome_unknown"
                try:
                    if row[1] == "evolve":
                        with self.background.operation() if self.background is not None else nullcontext():
                            response = self.client.evolve(user_id=self.settings.user_id, agent_id=self.settings.agent_id,
                                max_batches=json.loads(row[2])["max_batches"])
                        if not isinstance(response, dict) or response.get("success") is not True:
                            raise RuntimeError("hy_semantic_evolve_failed")
                        state = "partial" if (response.get("should_continue") or response.get("cycle_status") == "partial"
                            or response.get("batch_failures") or (response.get("cross_domain_sweeper") or {}).get("error")) else "completed"
                        reason = "native_cycle_requires_new_task" if state == "partial" else None
                    else:
                        self.client._loop_thread.run(self._expire_intentions())
                        state, reason = "completed", None
                except Exception:
                    # 不把外部提示、正文或凭据写入错误账本。
                    pass
                with self._condition, self._db() as db:
                    db.execute("UPDATE control SET value=value+1 WHERE key='revision'")
                    if row[1] == "evolve" and state == "completed":
                        if self._epoch(db) == epoch:
                            db.execute("UPDATE control SET value=? WHERE key='ready_epoch'", (epoch,))
                        else:
                            state, reason = "partial", "source_changed_during_evolve"
                    db.execute("UPDATE tasks SET state=?,finished=?,elapsed_ms=?,reason=? WHERE id=?",
                        (state, datetime.now(UTC).isoformat(), (perf_counter()-started)*1000, reason, row[0]))
                    self._condition.notify_all()

    async def _owned_nodes(self, layers):
        from hy_memory.models.memory import MemoryLayer
        result = await self.client._vector_store.list_by_user(self.settings.user_id,
            agent_id=self.settings.agent_id, layers=[MemoryLayer.from_string(layer) for layer in layers],
            include_sources=[SOURCE_NAMESPACE], limit=10001, with_vectors=False)
        if len(result) > 10000:
            raise ValueError("hy_semantic_invalidation_limit")
        return [node for node in result if node.source == SOURCE_NAMESPACE]

    async def _expire_intentions(self):
        for node in await self._owned_nodes(["l7_intention"]):
            if node.status.value == "active" and node.valid_until is not None and _expired(node.valid_until):
                await self.client._vector_store.update_payload(node.node_id, {"status": "archived"})

    async def _invalidate(self, source_ids):
        from hy_memory.models.memory import MemoryLayer, MemoryNode
        graph = self.client._graph_store
        nodes = await graph.get_all_nodes(MemoryNode.build_isolation_key(self.settings.user_id, self.settings.agent_id),
            layer=MemoryLayer.L6_SCHEMA, limit=10001)
        if len(nodes) > 10000 or any(node.source != SOURCE_NAMESPACE for node in nodes):
            raise ValueError("hy_semantic_graph_scope_or_limit_unproven")
        facts = await self._owned_nodes(["l2_fact", "l3_summary"])
        intentions = await self._owned_nodes(["l7_intention"])
        # 先完成所有范围检查，再隔离图和同源意图。失败时 ready_epoch 已失效。
        for node in nodes:
            if await graph.update_node(node.node_id, {"status": "archived"}) is False:
                raise RuntimeError("hy_semantic_graph_invalidation_failed")
        for node in intentions:
            meta = (node.custom or {}).get("meta")
            sources = _sources(meta)
            if sources is None or set(sources) & set(source_ids):
                await self.client._vector_store.update_payload(node.node_id, {"status": "archived"})
        for node in facts:
            custom = dict(node.custom or {})
            for key in tuple(custom):
                if key.startswith("s2_"):
                    custom.pop(key)
            await self.client._vector_store.update_payload(node.node_id, {"custom": custom})

    def begin_management(self, row):
        # 不排队等长模型调用。调用者的管理账本会保留未确认结果，不能绕过它。
        if not self._work.acquire(blocking=False):
            raise SemanticBusy("hy_semantic_management_busy")
        try:
            self.dirty()
            source_ids = _sources(row.get("meta"))
            if not source_ids:
                raise ValueError("hy_semantic_management_sources_unproven")
            self.client._loop_thread.run(self._invalidate(source_ids))
        except BaseException:
            self._work.release()
            raise

    def end_management(self):
        self._work.release()

    def close(self):
        with self._condition, self._db() as db:
            self._stopping = True
            db.execute("UPDATE tasks SET state='cancelled',reason='owner_close_before_claim' WHERE state='pending'")
            self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        # 活动任务不强行回滚。父进程终止后重启将 running 判为 uncertain。
        return not self._thread.is_alive()


def _expired(value):
    now = datetime.now(value.tzinfo) if value.tzinfo is not None else datetime.now()
    return now > value


async def graph_evidence(client, settings, node, *, _seen=()):
    """只承认可重新读取且同范围的原生证据；不从图正文猜平台来源。"""
    graph = client._graph_store
    if node.node_id in _seen or len(_seen) >= 3:
        return None, None
    refs = await graph._run("MATCH (m:Memory {node_id: $mid})-[:DERIVED_FROM]->(v:VdbRef) RETURN v.node_id LIMIT 17;",
        {"mid": node.node_id})
    evidence_ids = [row[0] for row in refs or []]
    if not evidence_ids:
        # core图式经basic归纳，追溯到实际事实证据才能继承平台纠正来源。
        # 无边的半成品不能只凭custom里写的raw ID冒充完整派生。
        basics = await graph._run("MATCH (b:Memory)-[:CROSS_ABSTRACTS_TO]->(m:Memory {node_id: $mid}) RETURN b LIMIT 17;",
            {"mid":node.node_id})
        if not basics or len(basics)>16:
            return None,None
        meta, identifiers = [],[]
        for row in basics:
            basic = graph._row_to_memory_node(row[0])
            if basic.user_id!=settings.user_id or basic.agent_id!=settings.agent_id or basic.source!=SOURCE_NAMESPACE:
                return None,None
            entries, ids = await graph_evidence(client,settings,basic,_seen=(*_seen,node.node_id))
            if not entries or not ids:
                return None,None
            meta.extend(entries)
            identifiers.extend(ids)
        identifiers = list(dict.fromkeys(identifiers))
        return (meta,identifiers) if len(identifiers)<=16 else (None,None)
    if not evidence_ids or len(evidence_ids) > 16:
        return None, None
    meta,covered_raw = [],set()
    for identifier in evidence_ids:
        if not isinstance(identifier, str) or len(identifier) > 256:
            return None, None
        evidence = await client._vector_store.get_by_id(identifier)
        if (evidence is None or evidence.user_id != settings.user_id or evidence.agent_id != settings.agent_id
                or evidence.source != SOURCE_NAMESPACE):
            return None, None
        entries = (evidence.custom or {}).get("meta")
        if not _sources(entries):
            return None, None
        meta.extend(entries)
        covered_raw.update(str(value) for value in (evidence.custom or {}).get("source_raw_memory_ids") or [])
        if evidence.source_raw_memory_id:
            covered_raw.add(evidence.source_raw_memory_id)
    expected = (node.custom or {}).get("evidence_raw_source_ids") or []
    if not isinstance(expected,list) or len(expected)>256 or not set(expected).issubset(covered_raw):
        return None,None
    return meta, evidence_ids


class SearchSourceReader:
    """回答来源读取也留在SDK原生search loop，避免回跳繁忙的System2 loop。"""

    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    def get(self, memory_id):
        node = self.client._search_loop_thread.run(self.client._vector_store.get_by_id(memory_id))
        if (node is None or node.user_id != self.settings.user_id or node.agent_id != self.settings.agent_id
                or node.source != SOURCE_NAMESPACE):
            return None
        return {"memory_id": node.node_id, "user_id": node.user_id, "content": node.content,
            "meta": (node.custom or {}).get("meta")}


async def read_profile(client, settings, budget):
    from .layer_data import LayerDataRPC
    item, _, reason = await LayerDataRPC(client, settings, budget)._profile(detail=True)
    if reason:
        raise ValueError("hy_semantic_profile_scope_unproven")
    if item is None:
        return {"profile": None}
    provenance = getattr(budget,"provenance",None)
    if provenance is not None:
        # L0原生聚合包含所有历史版本；不能仅隐藏一版后仍返回残留聚合。
        if not item["provenance"]["injection_allowed"]:
            return {"profile":None}
    # 字段及来源均由固定SDK纯合并函数/逐版本同范围读取取得；这里仅适配
    # 既有profile结果形状，不调用会扫描图目录/等待write loop的公开聚合API。
    sources = item["source_event_ids"]
    content=item["content"]
    if provenance is not None and not item["provenance"]["semantic_source_complete"]:
        from .provenance import PROFILE_INFERENCE_PREFIX
        content=PROFILE_INFERENCE_PREFIX+content
    return {"profile": {"memory_id": item["native_id"], "content": content, "layer": "l0_basic_info",
        "basic_info": item["basic_info"], "field_sources": item["field_sources"],
        "meta": [{"namespace": SOURCE_NAMESPACE, "source_event_ids": sources}] if sources else None}}


async def read_intentions(client, settings, embedding, *, limit=3):
    """复用原生 VDB/纯判重，刻意不调用原生惰性转层/异步删除。"""
    from hy_memory.models.memory import MemoryLayer, MemoryStatus
    from hy_memory.pipelines._retrieval.intention import _partition_duplicates, _get_dedup_threshold
    hits = await client._vector_store.search(query_embedding=embedding,
        user_ids=[settings.user_id], agent_ids=[settings.agent_id], layers=[MemoryLayer.L7_INTENTION],
        status_filter=[MemoryStatus.ACTIVE], only_latest=True, include_sources=[SOURCE_NAMESPACE],
        limit=30, score_threshold=0.0)
    survivors = [hit for hit in hits if hit.get("node") is not None
        and (hit["node"].valid_until is None or not _expired(hit["node"].valid_until))]
    if survivors:
        embeddings = await client._vector_store.get_embeddings([hit["node_id"] for hit in survivors])
        for hit in survivors:
            if hit["node_id"] in embeddings:
                hit["node"].embedding = list(embeddings[hit["node_id"]])
    kept, _ = _partition_duplicates(survivors, _get_dedup_threshold())
    provenance=getattr(client,"_platform_provenance",None)
    return [{"memory_id": hit["node_id"], "content": (await provenance.project_intention(hit["node"],hit["node"].content)
            if provenance is not None else hit["node"].content),
        "layer": "l7_intention", "score": hit.get("score"),
        "meta": (hit["node"].custom or {}).get("meta")} for hit in kept[:limit]]
