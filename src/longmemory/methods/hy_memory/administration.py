"""Hy 管理投影与受控串行操作；不把 SDK 的读后写包装成原生 CAS。"""

from contextlib import contextmanager, closing
from datetime import UTC, datetime
import hashlib
import json
import math
import sqlite3

from longmemory.methods.backend_contracts import ManagementCapabilities, MemoryItem, MemoryPage
from longmemory.methods.contracts import UnsupportedCapabilityError
from .sdk_bridge import HyResponseError, SOURCE_NAMESPACE, _item
from .management_rpc import ManagementRPC, HyManagementDenied, validate_management_write
from .observation import measured


class HyManagementConflict(ValueError):
    pass


class HyManagementUncertain(HyResponseError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HyAdministration:
    # 通用写契约要求原子修订；专属扩展使用不同的、明确受限的操作语义。
    capabilities = ManagementCapabilities(listing=True, detail=True)
    extension_namespace = "hy_memory"

    def __init__(self, method, *, serialized_writes=False):
        self.method = method
        self.serialized_writes = serialized_writes
        self._ledger_path = None
        method._management = self

    def source_overlay(self, item_id):
        """SDK update 不接收新来源；用平台审计补足真实用户纠正，不改写 SDK meta。"""
        return self.source_overlays((item_id,))[item_id]

    @measured('management_overlay_ms')
    def source_overlays(self, item_ids):
        """一次召回用同一连接批读；不跨请求缓存，不跳过不确定写隔离。"""
        unique = tuple(dict.fromkeys(item_ids))
        result = {item_id: ((), False) for item_id in unique}
        state = getattr(self.method._client, "state", None)
        if not unique or (self._ledger_path is None and (state is None or not (state.root / "management.sqlite3").exists())):
            return result
        with self._ledger() as db:
            # 参数分批避免SQLite变量上限；固定ID内仍按原时间/请求顺序组装。
            for offset in range(0, len(unique), 350):
                batch = unique[offset:offset + 350]
                marks = ','.join('?' for _ in batch)
                rows = db.execute('SELECT item_id,source_event_id,state,action FROM operations '
                    f'WHERE item_id IN ({marks}) ORDER BY item_id,occurred_at,request_id', batch).fetchall()
                grouped = {item_id: [] for item_id in batch}
                for row in rows:
                    grouped[row[0]].append(row[1:])
                for item_id, values in grouped.items():
                    result[item_id] = (tuple(dict.fromkeys(row[0] for row in values
                        if row[1] == 'completed' and row[2] == 'correct')),
                        any(row[1] in {'running', 'uncertain'} for row in values))
        return result

    def _record(self, row):
        if not isinstance(row, dict):
            raise HyResponseError("hy_management_invalid_response")
        if row.get("user_id") != self.method.settings.user_id or row.get("agent_id") != self.method.settings.agent_id:
            raise UnsupportedCapabilityError("hy_management_owner_scope_unsupported")
        item = _item(row, "management")
        # get.source 是 vdb/graph 存储通道；list.source 才可能是业务命名空间。
        if row.get("source") not in {None, "vdb", SOURCE_NAMESPACE} or (row.get("source") != SOURCE_NAMESPACE and item.source_event_ids is None):
            raise UnsupportedCapabilityError("hy_management_source_scope_unsupported")
        recorded = row.get("gmt_created")
        if recorded is not None:
            if type(recorded) not in (int, float) or not math.isfinite(recorded):
                raise HyResponseError("hy_management_invalid_time")
            try:
                recorded = datetime.fromtimestamp(recorded, UTC)
            except (ValueError, OverflowError, OSError):
                raise HyResponseError("hy_management_invalid_time") from None
        # request_id/elapsed_ms 是每次读取的临时数据，不能令相同持久状态的修订变化。
        revision = _digest({key: row.get(key) for key in ("memory_id", "content", "layer", "status",
            "meta", "gmt_created", "memory_at", "user_id", "agent_id", "is_latest", "supersedes",
            "superseded_by", "tags", "confidence", "custom")})
        return MemoryItem(item.memory_id, item.content, revision, item.layer or "hy_memory",
            item.source_event_ids, recorded_at=recorded, state=row.get("status"))

    def list_items(self, *, query="", state="active", limit=25, offset=0):
        if query or state != "active":
            raise UnsupportedCapabilityError("hy_listing_filter_unsupported")
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("hy_page_invalid")
        with self.method._lock:
            result = self.method.sdk_call("list_memories", user_id=self.method.settings.user_id,
                agent_id=self.method.settings.agent_id, limit=limit, offset=offset, order="desc")
            page = result.get("vdb") if isinstance(result, dict) else None
            if not isinstance(page, dict) or not isinstance(page.get("memories"), list) or type(page.get("total")) is not int or page["total"] < 0 or len(page["memories"]) > limit:
                raise HyResponseError("hy_management_invalid_response")
            # SDK list不含get的版本链/置信字段。统一从完整get构造修订，
            # 否则用户刚在列表读到的修订会被详情/写前检查误判为过期。
            items = tuple(self.get_item(self._record(row).item_id) for row in page["memories"])
            if page["total"] < offset + len(items) and items:
                raise HyResponseError("hy_management_invalid_response")
            return MemoryPage(items, page["total"], offset, limit)

    def get_item(self, item_id):
        if not isinstance(item_id, str) or not item_id.strip() or len(item_id) > 256:
            raise ValueError("hy_item_id_invalid")
        with self.method._lock:
            row = self.method.sdk_call("get", memory_id=item_id)
            if row is None:
                raise LookupError("hy_item_not_found")
            item = self._record(row)
            if item.item_id != item_id:
                raise HyResponseError("hy_management_id_mismatch")
            return item

    def correct_item(self, *args, **kwargs):
        raise UnsupportedCapabilityError("hy_atomic_revision_correction_unsupported")

    def delete_item(self, *args, **kwargs):
        raise UnsupportedCapabilityError("hy_atomic_revision_deletion_unsupported")

    def _protocol(self):
        self.method.wait_until_ready()
        function = getattr(self.method._client, "management_capabilities", None)
        if function is None:
            return {}
        value = function()
        if not isinstance(value, dict) or type(value.get("protocol")) is not int or value["protocol"] != 1 or any(
            type(value.get(key, False)) is not bool for key in
            ("profile", "history", "update", "delete", "exclusive_user_profile")
        ):
            raise HyResponseError("hy_management_protocol_invalid")
        return value

    @contextmanager
    def _ledger(self):
        # 此处只有可信 StateClient 持有取得了 engine.owner 的 state；HTTP 无法指定路径。
        if self._ledger_path is None:
            self.method.wait_until_ready()
            state = getattr(self.method._client, "state", None)
            if state is None or getattr(state, "_lease", None) is None:
                raise UnsupportedCapabilityError("hy_management_exclusive_owner_required")
            self._ledger_path = state.root / "management.sqlite3"
            with closing(sqlite3.connect(self._ledger_path)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS operations (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, action TEXT NOT NULL, item_id TEXT NOT NULL, source_event_id TEXT NOT NULL, revision TEXT NOT NULL, state TEXT NOT NULL, occurred_at TEXT NOT NULL, error_code TEXT)")
                # 新拥有者接管时 running 不能被当作可自动重发的失败。
                db.execute("UPDATE operations SET state='uncertain', error_code='hy_management_interrupted' WHERE state='running'")
        with closing(sqlite3.connect(self._ledger_path)) as db, db:
            yield db

    def _operations(self, *, item_id=None, limit=25, offset=0):
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("hy_page_invalid")
        with self._ledger() as db:
            db.row_factory = sqlite3.Row
            where, args = (" WHERE item_id=?", [item_id]) if item_id else ("", [])
            total = db.execute("SELECT COUNT(*) FROM operations" + where, args).fetchone()[0]
            rows = db.execute("SELECT request_id,action,item_id,source_event_id,revision,state,occurred_at,error_code FROM operations" + where + " ORDER BY occurred_at DESC,request_id LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
            return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def extension(self, operation, **arguments):
        layer_read = operation in {"layer_page", "layer_detail"}
        if not self.method._lock.acquire(blocking=operation != "mechanisms" and not layer_read):
            if layer_read:
                from .layer_data import HyLayerDataBusy
                raise HyLayerDataBusy("hy_layer_data_busy")
            raise RuntimeError("hy_mechanisms_busy")
        try:
            if layer_read:
                from .layer_data import validate_page, identifier, validate_result
                if self.method._closed or self.method._client is None:
                    raise HyResponseError("hy_layer_data_unavailable")
                if operation == "layer_page":
                    validate_page(**arguments)
                else:
                    validate_page(arguments["layer"])
                    identifier(arguments["item_id"])
                function = getattr(self.method._client, operation, None)
                if not callable(function):
                    raise UnsupportedCapabilityError("hy_layer_data_rpc_unavailable")
                result = function(**arguments)
                if result is None and operation == "layer_detail":
                    raise LookupError("hy_layer_item_not_found")
                return validate_result(result, operation, arguments["layer"], limit=arguments.get("limit", 20))
            if operation == "mechanisms":
                if arguments:
                    raise ValueError("hy_mechanisms_arguments_invalid")
                if self.method._closed:
                    raise RuntimeError("hy_mechanisms_unavailable")
                from .mechanisms import describe_mechanisms
                return describe_mechanisms(self.method)
            if operation == "workspace":
                protocol = self._protocol()
                return {"protocol": 1, "profile": bool(protocol.get("profile") and protocol.get("exclusive_user_profile")),
                    "history": bool(protocol.get("history")), "operations": True,
                    "correction": bool(self.serialized_writes and protocol.get("update")),
                    "deletion": bool(self.serialized_writes and protocol.get("delete")),
                    "revision_check": "exclusive_owner_serialized", "native_atomic_revision": False,
                    "full_text_search": False, "platform_sources_preserved": True}
            if operation == "operations":
                return self._operations(**arguments)
            if operation == "profile":
                caps = self._protocol()
                if not (caps.get("profile") and caps.get("exclusive_user_profile")):
                    raise UnsupportedCapabilityError("hy_profile_scope_not_proven")
                result = self.method.sdk_call("get_user_profile", user_id=self.method.settings.user_id)
                if not isinstance(result, dict) or "profile" not in result:
                    raise HyResponseError("hy_management_invalid_profile")
                # 组装画像常不带 agent/source；只允许已证明独占 user 的专用 RPC。
                row = result["profile"]
                if row is None:
                    return {"item": None}
                item = _item(row, "profile")
                if row.get("user_id") not in {None, self.method.settings.user_id} or item.layer != "l0_basic_info":
                    raise HyResponseError("hy_management_invalid_profile")
                # 聚合画像不是可 get/update 的普通条目；不捏造 agent/source/时间。
                return {"item": MemoryItem(item.memory_id, item.content,
                    _digest([item.memory_id, item.content, item.source_event_ids]), "l0_basic_info", item.source_event_ids)}
            if operation == "history":
                self.get_item(arguments["item_id"])
                if not self._protocol().get("history"):
                    raise UnsupportedCapabilityError("hy_history_unavailable")
                rows = self.method.sdk_call("history", memory_id=arguments["item_id"])
                if not isinstance(rows, list):
                    raise HyResponseError("hy_management_invalid_history")
                # SDK history 没有分页；有界投影，只暴露选定条目的字段。
                projected = []
                for row in rows[-100:]:
                    if not isinstance(row, dict) or row.get("memory_id") != arguments["item_id"]:
                        raise HyResponseError("hy_management_invalid_history")
                    if any(row.get(key) is not None and not isinstance(row[key], str) for key in ("event", "old_memory", "new_memory")) or (row.get("created_at") is not None and type(row["created_at"]) not in (str, int, float)):
                        raise HyResponseError("hy_management_invalid_history")
                    projected.append({key: row.get(key) for key in ("event", "old_memory", "new_memory", "created_at")})
                return {"items": projected, "limited": len(rows) > 100, "recording_complete": False}
            if operation in {"correct", "delete"}:
                return self._mutate(operation, **arguments)
            raise UnsupportedCapabilityError("hy_management_operation_unsupported")
        finally:
            self.method._lock.release()

    def _mutate(self, action, *, item_id, request_id, expected_revision, source, content=None):
        caps = self._protocol()
        if not self.serialized_writes or not caps.get("update" if action == "correct" else "delete"):
            raise UnsupportedCapabilityError("hy_serialized_management_not_enabled")
        from uuid import UUID
        try:
            valid_request = isinstance(request_id, str) and str(UUID(request_id)) == request_id
        except ValueError:
            valid_request = False
        if (not valid_request or not isinstance(expected_revision, str) or len(expected_revision) != 64
                or any(c not in "0123456789abcdef" for c in expected_revision)
                or (action == "correct" and (not isinstance(content, str) or not content.strip() or len(content) > 1000))):
            raise ValueError("hy_management_input_invalid")
        if (source.role != "user" or source.event_id != "hy-management:" + request_id
                or (action == "correct" and source.content != content)
                or (action == "delete" and source.content != "删除这条记忆：" + item_id)):
            raise ValueError("hy_management_source_invalid")
        payload_hash = _digest([action, item_id, expected_revision, source.event_id, source.content, content])
        with self._ledger() as db:
            previous = db.execute("SELECT payload_hash,state FROM operations WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if previous[0] != payload_hash:
                    raise HyManagementConflict("hy_management_request_conflict")
                if previous[1] != "completed":
                    raise HyManagementUncertain("hy_management_outcome_uncertain")
                return {"request_id": request_id, "state": "completed", "replayed": True,
                    "platform_sources_preserved": True}
            item = self.get_item(item_id)
            if db.execute("SELECT 1 FROM operations WHERE item_id=? AND state IN ('running','uncertain') LIMIT 1", (item_id,)).fetchone():
                raise HyManagementUncertain("hy_management_outcome_uncertain")
            if item.revision != expected_revision:
                raise HyManagementConflict("hy_management_revision_conflict")
            if item.kind not in {"l2_fact", "l3_summary"}:
                raise UnsupportedCapabilityError("hy_management_item_kind_read_only")
            try:
                ManagementRPC._identifier(item_id)
                row = self.method.sdk_call("get", memory_id=item_id)
                validate_management_write(row, self.method.settings, "update" if action == "correct" else "delete",
                    {"memory_id":item_id, **({"content":content} if action == "correct" else {})})
                current = self._record(row)
                if current.revision != expected_revision:
                    raise HyManagementConflict("hy_management_revision_conflict")
            except HyManagementDenied as error:
                # 已知未调用SDK写的拒绝不写running，更不能被记成uncertain；
                # worker仍独立复查相同规则，不能由平台预检查取代。
                raise HyManagementConflict(str(error)) from None
            db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,NULL)",
                (request_id, payload_hash, action, item_id, source.event_id, expected_revision,
                 "running", datetime.now(UTC).isoformat()))
        try:
            result = self.method.sdk_call("update" if action == "correct" else "delete",
                memory_id=item_id, **({"content": content} if action == "correct" else {}))
            if not isinstance(result, dict) or result.get("success") is not True:
                raise HyResponseError("hy_management_write_not_confirmed")
            if action == "correct":
                if result.get("memory_id") != item_id or self.get_item(item_id).content != content:
                    raise HyResponseError("hy_management_readback_mismatch")
            elif self.method.sdk_call("get", memory_id=item_id) is not None:
                raise HyResponseError("hy_management_readback_mismatch")
            with self._ledger() as db:
                db.execute("UPDATE operations SET state='completed' WHERE request_id=?", (request_id,))
        except Exception:
            with self._ledger() as db:
                db.execute("UPDATE operations SET state='uncertain',error_code='hy_management_outcome_uncertain' WHERE request_id=?", (request_id,))
            raise HyManagementUncertain("hy_management_outcome_uncertain") from None
        return {"request_id": request_id, "state": "completed", "replayed": False,
            "platform_sources_preserved": True}
