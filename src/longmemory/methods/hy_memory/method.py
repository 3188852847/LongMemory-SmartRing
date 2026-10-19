"""U MemoryMethod 的 Hy 适配；平台负责来源、重复事件和不确定投递。"""

import hashlib
import json
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from longmemory.methods.backend_contracts import ManagementCapabilities, MemoryItem, MemoryPage
from longmemory.methods.contracts import (
    MemorySupport, MethodCapabilities, ObservationResult, RetrievedTrace, UnsupportedCapabilityError,
)
from .sdk_bridge import HyResponseError, HySdkBridge, SDK_VERSION, _item


class HyMemoryMethod:
    name = "hy_memory_pro_chat"
    implementation_version = "sdk-" + SDK_VERSION + "-adapter-1"
    retrieval_name = "hy_chat_default_legacy"
    capabilities = MethodCapabilities(session_metadata=True)

    def __init__(self, *, settings, client_factory):
        self.settings = settings
        self._factory = client_factory
        self._client = self._bridge = None
        self._closed = False
        self._lock = RLock()

    def wait_until_ready(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("hy_method_closed")
            if self._client is None:
                self._client = self._factory()
                self._bridge = HySdkBridge(self._client, user_id=self.settings.user_id, agent_id=self.settings.agent_id)

    def observe(self, event):
        with self._lock:
            if event.role != "user":
                raise UnsupportedCapabilityError("hy_assistant_requires_platform_archive")
            self.wait_until_ready()
            self._bridge.add_event(event_id=event.event_id, role=event.role, content=event.content,
                occurred_at=event.occurred_at, session_id=event.session_id or "unscoped_session")
            # SDK 返回 raw/派生 ID 不等于每项 ADD/UPDATE 明细；不捏造写入过程。
            return ObservationResult(event.event_id, None)

    def archive(self, event):
        raise UnsupportedCapabilityError("hy_archive_requires_platform_journal")

    def recall(self, query):
        with self._lock:
            self.wait_until_ready()
            result = self._bridge.search(query, include_profile=self.settings.include_profile)
            selected = [item for item in result.items if item.channel == "normal"]
            if result.profile is not None:
                selected.insert(0, result.profile)
            items = tuple(RetrievedTrace(item.memory_id, item.content, item.source_event_ids) for item in selected)
            return MemorySupport(result.request_id or str(uuid4()), "\n".join(item.content for item in selected),
                items, self.retrieval_name, "hy_recall_may_mutate_state")

    def sdk_call(self, operation, **kwargs):
        with self._lock:
            self.wait_until_ready()
            if operation not in {"get", "list_memories", "diagnostics"}:
                raise UnsupportedCapabilityError("hy_sdk_operation_unsupported")
            return getattr(self._client, operation)(**kwargs)

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    if self._bridge:
                        self._bridge.close()
                finally:
                    self._closed = True


class HyAdministration:
    # SDK update/delete 无 expected_revision 原子比较，必须明确拒绝。
    capabilities = ManagementCapabilities(listing=True, detail=True)

    def __init__(self, method):
        self.method = method

    def _record(self, row):
        if not isinstance(row, dict):
            raise HyResponseError("hy_management_invalid_response")
        if row.get("user_id") != self.method.settings.user_id or row.get("agent_id") != self.method.settings.agent_id:
            raise UnsupportedCapabilityError("hy_management_owner_scope_unsupported")
        item = _item(row, "management")
        revision = hashlib.sha256(json.dumps({"item_id":item.memory_id,"content":item.content,
            "layer":item.layer,"source_event_ids":item.source_event_ids,"status":row.get("status")},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        recorded = row.get("gmt_created")
        if recorded is not None:
            if type(recorded) not in (int,float):
                raise HyResponseError("hy_management_invalid_time")
            recorded = datetime.fromtimestamp(recorded, UTC)
        # gmt_created 是记录时间；不把 memory_at 猜作事实生效区间。
        return MemoryItem(item.memory_id, item.content, revision, item.layer or "hy_memory",
            item.source_event_ids, recorded_at=recorded, state=row.get("status"))

    def list_items(self, *, query="", state="active", limit=25, offset=0):
        if query or state != "active":
            raise UnsupportedCapabilityError("hy_listing_filter_unsupported")
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("hy_page_invalid")
        result = self.method.sdk_call("list_memories", user_id=self.method.settings.user_id,
            agent_id=self.method.settings.agent_id, limit=limit, offset=offset, order="desc")
        page = result.get("vdb") if isinstance(result, dict) else None
        if not isinstance(page, dict) or not isinstance(page.get("memories"), list) or type(page.get("total")) is not int or page["total"] < 0 or len(page["memories"]) > limit:
            raise HyResponseError("hy_management_invalid_response")
        items = tuple(self._record(row) for row in page["memories"])
        if page["total"] < offset + len(items) and items:
            raise HyResponseError("hy_management_invalid_response")
        return MemoryPage(items, page["total"], offset, limit)

    def get_item(self, item_id):
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("hy_item_id_invalid")
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
