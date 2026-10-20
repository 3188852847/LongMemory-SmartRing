"""U MemoryMethod 的 Hy 适配；平台负责来源、重复事件和不确定投递。"""

from threading import RLock
from uuid import uuid4

from longmemory.methods.contracts import (
    MemorySupport, MethodCapabilities, ObservationResult, RetrievedTrace, UnsupportedCapabilityError,
)
from .sdk_bridge import HySdkBridge, SDK_VERSION, SOURCE_NAMESPACE, project_answer_content
from .administration import HyAdministration  # 保留既有公开导入路径。
from .observation import measured


class HyMemoryMethod:
    name = "hy_memory_pro_chat"
    implementation_version = "sdk-" + SDK_VERSION + "-adapter-1"
    retrieval_name = "hy_chat_default_legacy"
    capabilities = MethodCapabilities(session_metadata=True)

    @property
    def source_storage_version(self):
        """只有这两个已验证SDK2.0.3运行实现共享来源存储；非宽泛忽略版本。"""
        compatible = {"sdk-2.0.3-adapter-1", "sdk-2.0.3-semantic-adapter-2"}
        if (self.settings.sdk_version != "2.0.3" or SOURCE_NAMESPACE != "smartring_synthetic" or self.name != "hy_memory_pro_chat"
                or self.implementation_version not in compatible):
            raise ValueError("hy_source_runtime_storage_version_unproven")
        return "sdk-2.0.3-adapter-1"

    @property
    def source_compatible_versions(self):
        # semantic-adapter-2是5a4c1ec阶段新合成库已写入的旧绑定别名；
        # 保留其原文不回写，也不能据此接纳未来任意adapter/SDK版本。
        return (self.source_storage_version, "sdk-2.0.3-semantic-adapter-2")

    def __init__(self, *, settings, client_factory):
        self.settings = settings
        self._factory = client_factory
        self._client = self._bridge = None
        self._closed = False
        self._lock = RLock()
        self._background_write_enabled = True
        if settings.semantic_layers_enabled:
            self.implementation_version = "sdk-" + SDK_VERSION + "-semantic-adapter-2"
            self.retrieval_name = "hy_chat_default_legacy_semantic_v1"

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
            semantic = getattr(self.settings, "semantic_layers_enabled", False)
            selected = [item for item in result.items if item.channel == "normal" or semantic]
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
                content = project_answer_content(item.channel,item.content)
                items.append(RetrievedTrace(item.memory_id, content, source_ids))
            return MemorySupport(result.request_id or str(uuid4()), "\n".join(item.content for item in items),
                tuple(items), self.retrieval_name, "hy_management_uncertain_items_excluded" if excluded else "hy_recall_may_mutate_state")

    def sdk_call(self, operation, **kwargs):
        with self._lock:
            self.wait_until_ready()
            if operation not in {"get", "list_memories", "diagnostics", "get_user_profile", "history", "update", "delete",
                    "semantic_status", "semantic_task", "semantic_enqueue", "semantic_cancel", "semantic_pause"}:
                raise UnsupportedCapabilityError("hy_sdk_operation_unsupported")
            return getattr(self._client, operation)(**kwargs)

    def configure_background_writes(self, *, write_enabled):
        """由Runtime.configure同步同一写开关；只阻止未认领任务，不伪造回滚。"""
        if type(write_enabled) is not bool:
            raise ValueError("hy_background_write_flag_invalid")
        with self._lock:
            if self.settings.semantic_layers_enabled:
                self.sdk_call("semantic_pause", paused=not write_enabled)
            self._background_write_enabled = write_enabled

    def candidate_snapshot(self, *, query_embedding, limit=5):
        """候选读取不启动引擎、不归档话轮；调用方显式提供已有查询向量。"""
        from .semantic import SemanticBusy
        if not self._lock.acquire(blocking=False):
            raise SemanticBusy("hy_candidate_busy")
        try:
            if self._closed or self._client is None:
                raise RuntimeError("hy_candidate_not_initialized")
            result = self._client.candidate_snapshot(query_embedding=query_embedding,limit=limit)
            if result["read_status"] != "readable":
                return result
            management = getattr(self,"_management",None)
            overlays = management.source_overlays(identifier for row in result["items"]
                for identifier in row["evidence_memory_ids"]) if management else {}
            selected = []
            for row in result["items"]:
                values = [overlays.get(identifier,((),False)) for identifier in row["evidence_memory_ids"]]
                if any(blocked for _,blocked in values):
                    continue
                extra = tuple(source for sources,_ in values for source in sources)
                if extra:
                    row["source_event_ids"] = list(dict.fromkeys((row["source_event_ids"] or [])+list(extra)))
                row["content"] = project_answer_content(row["channel"],row["content"])
                selected.append(row)
            return {**result,"items":selected,"digest_scope":"native_items_before_platform_management_overlay"}
        finally:
            self._lock.release()

    def candidate_validate(self, *, snapshot_token, memory_digest=None):
        """提交前的时点校验；公共Runtime须在正式采用候选的同一临界区调用。"""
        from .semantic import SemanticBusy
        if not self._lock.acquire(blocking=False):
            raise SemanticBusy("hy_candidate_busy")
        try:
            if self._closed or self._client is None:
                return {"protocol":1,"valid":False,"reason_code":"owner_not_initialized"}
            result = self._client.candidate_validate(snapshot_token=snapshot_token)
            if result["valid"] and memory_digest is not None and result["memory_digest"] != memory_digest:
                return {"protocol":1,"valid":False,"reason_code":"memory_digest_mismatch"}
            return result
        finally:
            self._lock.release()

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    if self._bridge:
                        self._bridge.close()
                finally:
                    self._closed = True
