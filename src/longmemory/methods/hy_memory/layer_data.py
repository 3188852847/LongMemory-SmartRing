"""2.0.3独占SDK实例内的有界内容读取；不调用search、模型或第二存储客户端。"""

from datetime import UTC, datetime
import math
from pathlib import Path

from .sdk_bridge import SDK_VERSION, SOURCE_NAMESPACE, HyResponseError, _sources


LAYERS = tuple(f"l{number}_{name}" for number, name in enumerate(
    ("basic_info", "raw", "fact", "summary", "identity", "knowledge", "schema", "intention")))
STATES = ("all", "active", "superseded", "negated", "conflicted", "shadow", "archived")
PROFILE_LIMIT = 128


class HyLayerDataBusy(RuntimeError):
    pass


def identifier(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or value in {".", ".."} or any(ord(c) < 32 or c in "/\\" for c in value)):
        raise ValueError("hy_layer_data_invalid_id")
    return value


def validate_page(layer, limit=20, offset=0, state="all"):
    if (layer not in LAYERS or type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or not 0 <= offset <= 10000 or state not in STATES
            or (layer == LAYERS[0] and state != "all")):
        raise ValueError("hy_layer_data_invalid_page")


def _time(value):
    if value in (None, ""):
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise HyResponseError("hy_layer_data_invalid_time")
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        raise HyResponseError("hy_layer_data_invalid_time") from None


def _links(value, maximum=16):
    if value is None or value == "":
        return [], False
    if not isinstance(value, list):
        raise HyResponseError("hy_layer_data_invalid_links")
    return [identifier(item) for item in value[:maximum]], len(value) > maximum


def _record(payload, *, detail=False, summary=False):
    content = payload.get("content")
    if not isinstance(content, str):
        raise HyResponseError("hy_layer_data_invalid_content")
    maximum = 512 if summary else 32768 if detail else 1024
    old, old_limited = _links(payload.get("supersedes"), 4 if summary else 16)
    new, new_limited = _links(payload.get("superseded_by"), 4 if summary else 16)
    custom = payload.get("custom") or {}
    meta = custom.get("meta") if isinstance(custom, dict) else None
    bounded_meta = (isinstance(meta, list) and len(meta) <= 128 and all(
        isinstance(entry, dict) and isinstance(entry.get("source_event_ids"), list)
        and len(entry["source_event_ids"]) <= 16 for entry in meta))
    source_ids = _sources(meta) if bounded_meta else None
    if source_ids is not None and (len(source_ids) > (8 if summary else 16) or any(len(value) > 256 for value in source_ids)):
        source_ids = None
    raw = payload.get("source_raw_memory_id")
    return {"item_id": identifier(payload["node_id"]), "native_id": payload["node_id"],
        "kind": "stored_record", "layer": payload["layer"],
        "content": content[:maximum], "content_chars": len(content), "content_truncated": len(content) > maximum,
        "status": payload.get("status"), "is_latest": payload.get("is_latest"),
        "recorded_at": _time(payload.get("gmt_created")), "memory_at": _time(payload.get("memory_at")),
        "valid_from": _time(payload.get("valid_from")), "valid_until": _time(payload.get("valid_until")),
        "supersedes": old, "superseded_by": new, "version_links_limited": old_limited or new_limited,
        "source_event_ids": list(source_ids) if source_ids is not None else None,
        "source_raw_memory_id": identifier(raw) if raw else None}


def validate_result(result, operation, layer, *, limit=20):
    """主进程再验证白名单，防止坏RPC将任意custom/config字段透传HTTP。"""
    base = {"schema_version", "layer", "sdk_support", "generation_state", "read_status", "data_state", "coverage", "reason_code", "observed_at"}
    extra = {"item", "versions"} if operation == "layer_detail" else {"items", "total", "count_scope", "has_more", "limit", "offset", "state"}
    if (not isinstance(result, dict) or set(result) != base | extra or result.get("schema_version") != 1
            or result.get("layer") != layer or result.get("read_status") not in {"readable", "partial", "unavailable"}
            or result.get("data_state") not in {"present", "empty", "unknown"}):
        raise HyResponseError("hy_layer_data_invalid_response")
    records = ([result["item"]] if result.get("item") is not None else []) if operation == "layer_detail" else result["items"]
    versions = result.get("versions")
    if (not isinstance(records, list) or len(records) > (1 if operation == "layer_detail" else limit)
            or (versions is not None and (not isinstance(versions, list) or len(versions) > PROFILE_LIMIT))):
        raise HyResponseError("hy_layer_data_invalid_response")
    record_fields = {"item_id", "native_id", "kind", "layer", "content", "content_chars", "content_truncated", "status", "is_latest",
        "recorded_at", "memory_at", "valid_from", "valid_until", "supersedes", "superseded_by", "version_links_limited", "source_event_ids", "source_raw_memory_id"}
    for record in records + (versions or []):
        aggregate = isinstance(record, dict) and record.get("kind") == "aggregate_profile"
        semantic_fields = {"semantic_kind", "execution_authorized", "derivation_state", "evidence_memory_ids", "updated_at"}
        semantic = isinstance(record, dict) and "semantic_kind" in record
        provenance = isinstance(record,dict) and "provenance" in record
        fields = record_fields | ({"basic_info", "field_sources", "stored_version_count"} if aggregate else set()) | (semantic_fields if semantic else set()) | ({"provenance"} if provenance else set())
        if (not isinstance(record, dict) or set(record) != fields or record.get("layer") != layer
                or (aggregate and (layer != LAYERS[0] or record.get("item_id") != "profile"))
                or not isinstance(record.get("content"), str) or len(record["content"]) > 32768
                or type(record.get("content_chars")) is not int or record["content_chars"] < len(record["content"])
                or type(record.get("content_truncated")) is not bool
                or record.get("status") not in STATES[1:] or type(record.get("is_latest")) not in {bool, type(None)}):
            raise HyResponseError("hy_layer_data_invalid_response")
        if semantic and (layer not in LAYERS[6:] or record["execution_authorized"] is not False
                or record["semantic_kind"] not in {"model_inference", "future_intention"}
                or record["derivation_state"] not in {"ready", "isolated", "expired", "stored"}
                or (record["evidence_memory_ids"] is not None and (not isinstance(record["evidence_memory_ids"], list)
                    or len(record["evidence_memory_ids"]) > 16))):
            raise HyResponseError("hy_layer_data_invalid_semantics")
        if provenance:
            value = record["provenance"]
            if (layer not in (LAYERS[0],*LAYERS[2:5],LAYERS[7]) or not isinstance(value,dict)
                    or set(value)!={"status","semantic_source_complete","dependency_basis","injection_allowed"}
                    or value["status"] not in {"verbatim_user","explicit_correction","model_inference_unverified"}
                    or value["dependency_basis"] not in {"explicit_correction","scope_context_envelope","legacy_unobserved","verbatim_current_input","raw_exact_match"}
                    or type(value["semantic_source_complete"]) is not bool or type(value["injection_allowed"]) is not bool
                    or value["semantic_source_complete"] != (value["status"]!="model_inference_unverified")):
                raise HyResponseError("hy_layer_data_invalid_provenance")
        identifier(record["item_id"])
        identifier(record["native_id"])
        for key in ("supersedes", "superseded_by"):
            links = record[key]
            if not isinstance(links, list) or len(links) > 64:
                raise HyResponseError("hy_layer_data_invalid_response")
            for value in links:
                identifier(value)
        sources = record["source_event_ids"]
        if sources is not None and (not isinstance(sources, list) or len(sources) > 128 or any(
                not isinstance(value, str) or not value or len(value) > 256 for value in sources)):
            raise HyResponseError("hy_layer_data_invalid_response")
        if aggregate:
            if not isinstance(record["basic_info"], dict) or not isinstance(record["field_sources"], dict):
                raise HyResponseError("hy_layer_data_invalid_response")
            for source in record["field_sources"].values():
                if not isinstance(source, dict) or set(source) != {"native_id", "source_event_ids"}:
                    raise HyResponseError("hy_layer_data_invalid_response")
    return result


class LayerDataRPC:
    OPERATIONS = {"layer_page", "layer_detail"}

    def __init__(self, client, settings, budget):
        self.client, self.settings, self.budget = client, settings, budget

    def _base(self, layer):
        support = "historical" if layer == LAYERS[4] else "reserved" if layer == LAYERS[5] else "implemented"
        generation = "historical" if layer == LAYERS[4] else "reserved" if layer == LAYERS[5] else (
            "disabled" if layer in LAYERS[6:] and not self.settings.semantic_layers_enabled else "configured")
        return {"schema_version": 1, "layer": layer, "sdk_support": support, "generation_state": generation,
                "read_status": "readable", "data_state": "unknown", "coverage": "vdb_complete",
                "reason_code": None, "observed_at": datetime.now(UTC).isoformat()}

    def _available(self):
        from .management_rpc import owner_lease_held
        store = getattr(self.client, "_vector_store", None)
        config = getattr(self.client, "_config", None)
        workspace = getattr(self.budget, "management_workspace", None)
        return (getattr(self.budget, "actual_sdk_version", None) == SDK_VERSION
            and workspace is not None and owner_lease_held(workspace)
            and type(store).__name__ == "ChromaVectorStore" and store._collection is not None
            and config is not None and not config.vector_store.host
            and ((getattr(self.client, "_graph_store", None) is None and not config.enable_graph)
                or (self.settings.semantic_layers_enabled and getattr(self.budget, "semantic", None) is not None
                    and getattr(self.client._graph_store, "_available", False))))

    def _scope(self, layer, state, *, user_level=False):
        conditions = [{"user_id": {"$eq": self.settings.user_id}}, {"layer": {"$eq": layer}}]
        if not user_level:
            conditions.extend(({"agent_id": {"$eq": self.settings.agent_id}},
                               {"source": {"$eq": SOURCE_NAMESPACE}}))
        if state != "all":
            conditions.append({"status": {"$eq": state}})
        return {"$and": conditions}

    async def _rows(self, layer, state, *, limit, offset=0, item_id=None, user_level=False):
        from hy_memory.data.vector_store_chroma import _run_in_vdb_pool
        store = self.client._vector_store
        arguments = {"where": self._scope(layer, state, user_level=user_level),
                     "include": ["metadatas"], "limit": limit, "offset": offset}
        if item_id is not None:
            arguments["ids"] = [store._node_id_to_point_id(item_id)]
        result = await _run_in_vdb_pool(store._collection.get, **arguments)
        ids, metas = result.get("ids"), result.get("metadatas")
        if not isinstance(ids, list) or not isinstance(metas, list) or len(ids) != len(metas) or len(ids) > limit:
            raise HyResponseError("hy_layer_data_invalid_page")
        rows = []
        for point_id, meta in zip(ids, metas):
            if not isinstance(meta, dict):
                raise HyResponseError("hy_layer_data_invalid_record")
            payload = store._chroma_metadata_to_payload(meta)
            if (payload.get("user_id") != self.settings.user_id or payload.get("layer") != layer
                    or (state != "all" and payload.get("status") != state)
                    or store._node_id_to_point_id(identifier(payload.get("node_id"))) != point_id
                    or (item_id is not None and payload["node_id"] != item_id)):
                raise HyResponseError("hy_layer_data_scope_mismatch")
            if not user_level and (payload.get("agent_id") != self.settings.agent_id or payload.get("source") != SOURCE_NAMESPACE):
                raise HyResponseError("hy_layer_data_scope_mismatch")
            custom = payload.get("custom")
            meta_entries = custom.get("meta") if isinstance(custom, dict) else None
            if not user_level and isinstance(meta_entries, list) and any(
                    isinstance(entry, dict) and entry.get("namespace") not in {None, SOURCE_NAMESPACE} for entry in meta_entries):
                raise HyResponseError("hy_layer_data_scope_mismatch")
            rows.append(payload)
        return rows

    def _graph_coverage(self, result):
        if result["layer"] not in LAYERS[6:]:
            return
        if self.settings.semantic_layers_enabled and getattr(self.budget, "semantic", None) is not None:
            return
        workspace = getattr(self.budget, "management_workspace", None)
        graph = self.client._config.graph_store
        # 只检查标准worker固定本地路径；绝不调用SDK的临时开图库回退。
        known = (workspace is not None and graph.provider == "kuzu"
                 and Path(graph.db_path) == Path(workspace) / "sdk" / "graph")
        if not known or Path(graph.db_path).exists() or Path(str(graph.db_path) + ".wal").exists():
            result.update(read_status="partial", coverage="vdb_only_graph_unopened", reason_code="graph_store_not_open")

    def _profile_scope(self):
        from .management_rpc import owner_lease_held
        workspace = getattr(self.budget, "management_workspace", None)
        return (getattr(self.budget, "management_profile_scope_proven", False) is True
                and workspace is not None and owner_lease_held(workspace))

    async def _profile(self, *, detail=False):
        if not self._profile_scope():
            return None, None, "profile_scope_unproven"
        rows = await self._rows(LAYERS[0], "all", limit=PROFILE_LIMIT + 1, user_level=True)
        if len(rows) > PROFILE_LIMIT:
            return None, None, "profile_history_limit"
        if not rows:
            return None, [], None
        nodes = []
        store = self.client._vector_store
        for row in rows:
            custom = row.get("custom")
            meta = custom.get("meta") if isinstance(custom, dict) else None
            if (row.get("agent_id") not in {None, "", self.settings.agent_id}
                    or row.get("source") not in {"default", SOURCE_NAMESPACE}
                    or not isinstance(meta, list) or not meta or len(meta) > 128
                    or any(not isinstance(m, dict) or m.get("namespace") != SOURCE_NAMESPACE for m in meta)
                    or not isinstance(custom.get("basic_info_kv"), dict)):
                return None, None, "profile_scope_unproven"
            if len(custom["basic_info_kv"]) > 64:
                return None, None, "profile_fields_limit"
            nodes.append(store._payload_to_node(row))
        from hy_memory.agent.tools.basic_profile import _assemble_full_kv_from_nodes, _latest_l0_heads_from_nodes, _render_content, _node_timestamp
        # SDK纯函数，不调用profile API的图/日志/无界来源扩展。
        full = _assemble_full_kv_from_nodes(list(nodes))
        heads = _latest_l0_heads_from_nodes(nodes)
        if not heads:
            return None, None, "profile_head_unavailable"
        if (len(full) > 64 or any(not isinstance(k, str) or len(k) > 128
                or type(v) not in (str, int, float, bool, type(None)) or len(str(v)) > 2048
                or (type(v) is float and not math.isfinite(v)) for k, v in full.items())):
            return None, None, "profile_fields_limit"
        head = next(row for row in rows if row["node_id"] == heads[0].node_id)
        item = _record(head, detail=detail)
        content = _render_content(full, field_order=list(self.client._config.basic_profile.effective_fields()) + sorted(
            key for key in full if key not in self.client._config.basic_profile.effective_fields()))
        maximum = 32768 if detail else 1024
        item.update(item_id="profile", kind="aggregate_profile", content=content[:maximum],
            content_chars=len(content), content_truncated=len(content) > maximum,
            basic_info=full, stored_version_count=len(rows))
        origins, reconstructed = {}, {}
        for node in sorted(nodes, key=_node_timestamp):
            row = next(r for r in rows if r["node_id"] == node.node_id)
            projected = _record(row)
            for key in node.custom["basic_info_kv"]:
                reconstructed[key] = node.custom["basic_info_kv"][key]
                origins[key] = {"native_id": node.node_id, "source_event_ids": projected["source_event_ids"]}
        if reconstructed != full:
            origins = {key: {"native_id": None, "source_event_ids": None} for key in full}
        item["field_sources"] = origins
        # 链头来源不能冒充全部当前字段来源。
        sources = [entry["source_event_ids"] for entry in origins.values()]
        item["source_event_ids"] = list(dict.fromkeys(s for ids in sources for s in ids)) if all(ids is not None for ids in sources) else None
        if item["source_event_ids"] is not None and len(item["source_event_ids"]) > 16:
            item["source_event_ids"] = None
        provenance=getattr(self.budget,"provenance",None)
        if provenance is not None:
            # 聚合完整性必须覆盖全部存储版本；单字段/链头来源不能代表全画像。
            item["provenance"]=provenance.profile_description(nodes)
        return item, [_record(row, summary=True) for row in rows], None

    async def _execute(self, operation, arguments):
        layer = arguments["layer"]
        result = self._base(layer)
        detail = operation == "layer_detail"
        if not self._available():
            result.update(read_status="unavailable", coverage="unavailable", reason_code="storage_backend_unavailable")
        if layer == LAYERS[0] and result["read_status"] == "readable":
            item, versions, reason = await self._profile(detail=detail)
            if reason:
                result.update(read_status="unavailable", coverage="unavailable", reason_code=reason)
            elif detail:
                if arguments["item_id"] == "profile":
                    return {**result, "data_state": "present", "item": item, "versions": versions} if item else None
                version = next((row for row in versions if row["item_id"] == arguments["item_id"]), None)
                if version is None:
                    return None
                rows = await self._rows(layer, "all", limit=1, item_id=arguments["item_id"], user_level=True)
                return {**result, "data_state": "present", "item": _record(rows[0], detail=True), "versions": None}
            else:
                items = [item] if item else []
                offset, limit = arguments["offset"], arguments["limit"]
                return {**result, "data_state": "present" if item else "empty", "items": items[offset:offset + limit],
                    "total": len(items), "count_scope": "aggregate_profile", "has_more": False,
                    "limit": limit, "offset": offset, "state": "all"}
        if result["read_status"] == "readable":
            if layer == LAYERS[6] and self.settings.semantic_layers_enabled:
                return await self._graph_page(result, operation, arguments)
            self._graph_coverage(result)
            rows = await self._rows(layer, "all" if detail else arguments["state"],
                limit=1 if detail else arguments["limit"] + 1,
                offset=0 if detail else arguments["offset"], item_id=arguments.get("item_id"))
            provenance = getattr(self.budget,"provenance",None)
            async def project(row, *, detail=False):
                item = self._project(row,detail=detail)
                if provenance is not None and layer in (*LAYERS[2:5],LAYERS[7]):
                    item["provenance"] = await provenance.describe(self.client._vector_store._payload_to_node(row))
                return item
            if detail:
                if rows:
                    return {**result, "data_state": "present", "item": await project(rows[0], detail=True), "versions": None}
                if result["coverage"] != "vdb_complete":
                    return {**result, "read_status": "unavailable", "item": None, "versions": None}
                return None
            limit, offset = arguments["limit"], arguments["offset"]
            more = len(rows) > limit
            total = offset + len(rows) if not more and (rows or offset == 0) and result["coverage"] == "vdb_complete" else None
            return {**result, "data_state": "present" if rows else "empty" if total == 0 else "unknown",
                "items": [await project(row) for row in rows[:limit]], "total": total,
                "count_scope": "owner_agent_source_layer_state_vdb", "has_more": more,
                "limit": limit, "offset": offset, "state": arguments["state"]}
        if detail:
            return {**result, "item": None, "versions": None}
        return {**result, "items": [], "total": None, "count_scope": "aggregate_profile" if layer == LAYERS[0] else "owner_agent_source_layer_state_vdb",
                "has_more": None, "limit": arguments["limit"], "offset": arguments["offset"], "state": arguments["state"]}

    def _project(self, payload, *, detail=False):
        item = _record(payload, detail=detail)
        if self.settings.semantic_layers_enabled and payload["layer"] == LAYERS[7]:
            from .semantic import _expired
            until = payload.get("valid_until")
            expired = until is not None and _expired(datetime.fromtimestamp(until, UTC))
            item.update(semantic_kind="future_intention", execution_authorized=False,
                derivation_state="expired" if expired else "stored", evidence_memory_ids=None,
                updated_at=_time(payload.get("gmt_modified")))
        return item

    async def _graph_page(self, result, operation, arguments):
        from hy_memory.models.memory import MemoryNode
        from .semantic import graph_evidence
        detail = operation == "layer_detail"
        graph = self.client._graph_store
        params = {"ik": MemoryNode.build_isolation_key(self.settings.user_id, self.settings.agent_id), "source": SOURCE_NAMESPACE}
        conditions = ["m.isolation_key=$ik", "m.source=$source", "m.layer='l6_schema'"]
        if detail:
            conditions.append("m.node_id=$mid")
            params["mid"] = arguments["item_id"]
        elif arguments["state"] != "all":
            conditions.append("m.status=$state")
            params["state"] = arguments["state"]
        limit, offset = (1, 0) if detail else (arguments["limit"], arguments["offset"])
        rows = await graph._run("MATCH (m:Memory) WHERE " + " AND ".join(conditions)
            + f" RETURN m ORDER BY m.node_id SKIP {offset} LIMIT {limit + (not detail)};", params)
        if rows is None:
            raise HyResponseError("hy_layer_graph_unavailable")
        projected = []
        state = self.budget.semantic.gate()["schema_state"]
        for row in rows[:limit]:
            node = graph._row_to_memory_node(row[0])
            if node.user_id != self.settings.user_id or node.agent_id != self.settings.agent_id or node.source != SOURCE_NAMESPACE:
                raise HyResponseError("hy_layer_graph_scope_unproven")
            meta, evidence_ids = await graph_evidence(self.client, self.settings, node)
            payload = {key: getattr(node, key, None) for key in ("node_id", "content", "is_latest", "supersedes", "superseded_by", "source_raw_memory_id")}
            payload.update(layer=LAYERS[6], status=node.status.value, custom={"meta": meta})
            for key in ("gmt_created", "gmt_modified", "memory_at", "valid_from", "valid_until"):
                value = getattr(node, key, None)
                payload[key] = value.timestamp() if value is not None else None
            item = _record(payload, detail=detail)
            item.update(semantic_kind="model_inference", execution_authorized=False,
                derivation_state=state if meta and evidence_ids else "isolated", evidence_memory_ids=evidence_ids, updated_at=_time(payload["gmt_modified"]))
            projected.append(item)
        result.update(coverage="graph_complete", reason_code="schema_injection_isolated" if state == "isolated" else None,
            data_state="present" if projected else "unknown")
        legacy = await self._rows(LAYERS[6], "all", limit=1)
        if legacy:
            result.update(read_status="partial", coverage="graph_only_legacy_vdb_present", reason_code="legacy_vdb_schema_not_in_graph_page")
        if detail:
            return {**result, "item": projected[0], "versions": None} if projected else None
        more = len(rows) > limit
        total = offset + len(rows) if not more and (rows or offset == 0) else None
        if legacy:
            total = None
        if total == 0:
            result["data_state"] = "empty"
        return {**result, "items": projected, "total": total, "has_more": more,
            "count_scope": "owner_agent_source_layer_state_graph", "limit": limit, "offset": offset, "state": arguments["state"]}

    def execute(self, operation, arguments):
        if operation not in self.OPERATIONS or not isinstance(arguments, dict):
            raise ValueError("hy_layer_data_invalid_operation")
        expected = {"layer", "item_id"} if operation == "layer_detail" else {"layer", "limit", "offset", "state"}
        if set(arguments) != expected:
            raise ValueError("hy_layer_data_invalid_arguments")
        if operation == "layer_detail":
            validate_page(arguments["layer"])
            identifier(arguments["item_id"])
        else:
            validate_page(**arguments)
        loop = self.client._search_loop_thread if self.settings.semantic_layers_enabled else self.client._loop_thread
        result = loop.run(self._execute(operation, arguments))
        if isinstance(result, dict):
            result["observed_at"] = datetime.now(UTC).isoformat()
        return result
