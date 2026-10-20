"""U MemoryMethod 的 Hy 适配；平台负责来源、重复事件和不确定投递。"""

from threading import RLock
from uuid import uuid4

from longmemory.methods.contracts import (
    MemorySupport, MethodCapabilities, ObservationResult, RetrievedTrace, UnsupportedCapabilityError,
)
from .sdk_bridge import HySdkBridge, SDK_VERSION
from .administration import HyAdministration  # 保留既有公开导入路径。
from .observation import measured


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

    @measured('hy_observe_ms')
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

    @measured('hy_recall_ms')
    def recall(self, query):
        with self._lock:
            self.wait_until_ready()
            result = self._bridge.search(query, include_profile=self.settings.include_profile)
            selected = [item for item in result.items if item.channel == "normal"]
            if result.profile is not None:
                selected.insert(0, result.profile)
            items, excluded = [], False
            management = getattr(self, "_management", None)
            overlays = None
            if management and callable(getattr(management, 'source_overlays', None)):
                overlays = management.source_overlays(memory_id for item in selected
                    for memory_id in (item.visible_memory_ids or (item.memory_id,)))
            for item in selected:
                sources, uncertain = (), False
                # SDK把可见旧版本正文拼在链头内；必须同时检查每个可见版本的
                # 管理来源和未确认状态，不能仅按新链头ID放行历史正文。
                for memory_id in item.visible_memory_ids or (item.memory_id,):
                    overlay, blocked = (overlays[memory_id] if overlays is not None else
                        management.source_overlay(memory_id) if management else ((), False))
                    sources += overlay
                    uncertain = uncertain or blocked
                if uncertain:
                    excluded = True
                    continue
                source_ids = tuple(dict.fromkeys((item.source_event_ids or ()) + sources)) if sources else item.source_event_ids
                items.append(RetrievedTrace(item.memory_id, item.content, source_ids))
            return MemorySupport(result.request_id or str(uuid4()), "\n".join(item.content for item in items),
                tuple(items), self.retrieval_name, "hy_management_uncertain_items_excluded" if excluded else "hy_recall_may_mutate_state")

    def sdk_call(self, operation, **kwargs):
        with self._lock:
            self.wait_until_ready()
            if operation not in {"get", "list_memories", "diagnostics", "get_user_profile", "history", "update", "delete"}:
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
