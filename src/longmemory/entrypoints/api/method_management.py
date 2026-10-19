"""旧管理 DTO 的中立投影，以及新引擎对旧管理端点的明确拒绝。"""

from datetime import datetime

from longmemory.methods.backend_contracts import (
    ManagementCapabilities, MemoryItem, MemoryPage,
)
from .errors import MemoryAccessError


class LegacyMemoryAdministration:
    def __init__(self, backend):
        self.backend = backend
        self.capabilities = ManagementCapabilities(
            listing=True, detail=True, correction=backend.allow_correction,
            deletion=backend.allow_delete, temporal_history=True,
            scenarios=backend.allow_scenario_management, personas=backend.allow_persona_management,
        )

    @staticmethod
    def _item(data):
        return MemoryItem(data["id"], data["content"], data["revision"], "atomic_fact",
            tuple(source["source_message_id"] for source in data["sources"]),
            **{key: datetime.fromisoformat(data[key]) if data.get(key) else None
               for key in ("recorded_at", "valid_from", "valid_to")}, state=data["state"])

    def list_items(self, **query):
        page = self.backend.list_page(**query)
        return MemoryPage(tuple(self.get_item(item["id"]) for item in page["items"]),
                          page["total"], page["offset"], page["limit"])

    def get_item(self, item_id):
        return self._item(self.backend.get(item_id))

    def correct_item(self, item_id, content, *, expected_revision, source):
        if source.session_id is not None:
            from longmemory.methods.contracts import UnsupportedCapabilityError
            raise UnsupportedCapabilityError("legacy_correction_session_metadata_unsupported")
        result = self.backend.correct(item_id, content, expected_revision, source_event=source)
        return self.get_item(result["new_memory_id"])

    def delete_item(self, item_id, *, expected_revision):
        self.backend.delete(item_id, expected_revision)


class UnsupportedLegacyMemoryBackend:
    """让已公开的旧端点返回 501，绝不拿平台原文库当成旧引擎库打开。"""

    def __init__(self, runtime):
        self.runtime = runtime

    def info(self):
        state = self.runtime.status()
        return {"configured": True, "database": None, "method": state["method"],
                "representation": "method_defined", "management_api": "/api/memory-engine",
                "management_capabilities": state["management_capabilities"],
                **{key: False for key in (
                    "allow_delete", "allow_clear", "allow_correction", "allow_change",
                    "allow_promote_source", "allow_l1_quality_review",
                    "semantic_relation_preview_available", "allow_scenario_management",
                    "allow_persona_management", "scenario_model_preview_available",
                    "persona_model_preview_available")}}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        # 路由函数名是本仓库白名单，HTTP 不能选择任意 Python 方法。
        def unsupported(*args, **kwargs):
            raise MemoryAccessError("memory_backend_capability_unsupported", 501)
        return unsupported
