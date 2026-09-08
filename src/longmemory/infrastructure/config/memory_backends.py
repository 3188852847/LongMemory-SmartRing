"""圆屏记忆后端选择；只保存非敏感指针，不搬运任何记忆数据。"""

from __future__ import annotations

import json
import os
from pathlib import Path


BACKENDS = {
    "longmemory": {
        "label": "LongMemory（当前系统）",
        "provider": "LongMemory",
        "description": "分层、可追溯、可纠正的项目记忆系统。",
        "persistent": True,
    },
    "xiaozhi_local": {
        "label": "小智本地摘要",
        "provider": "mem_local_short",
        "description": "小智自带的单份 LLM 摘要；查询时注入整份摘要。",
        "persistent": True,
    },
    "none": {
        "label": "无长期记忆（速度基线）",
        "provider": "nomem",
        "description": "只保留当前连接内的对话，不跨会话保存或检索。",
        "persistent": False,
    },
}


class MemoryBackendStore:
    """管理下次圆屏启动使用的后端；运行中的服务不会热切换。"""

    def __init__(self, root: Path, *, current_backend: str = "longmemory"):
        self.root = Path(root).resolve()
        self.selection_path = self.root / "data/control/memory-backend.json"
        self.current_backend = self._backend(current_backend)

    @staticmethod
    def _backend(value: str) -> str:
        if value not in BACKENDS:
            raise ValueError("unknown_memory_backend")
        return value

    def selected(self) -> str:
        try:
            body = json.loads(self.selection_path.read_text(encoding="utf-8"))
            value = body.get("selected_backend") if isinstance(body, dict) else None
        except (OSError, ValueError, TypeError):
            value = None
        return value if value in BACKENDS else "longmemory"

    def describe(self) -> dict:
        selected = self.selected()
        return {
            "current_backend": self.current_backend,
            "next_start_backend": selected,
            "restart_required": selected != self.current_backend,
            "backends": [
                {"id": key, **value} for key, value in BACKENDS.items()
            ],
        }

    def select(self, backend: str) -> dict:
        backend = self._backend(backend)
        body = {"version": 1, "selected_backend": backend}
        self.selection_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.selection_path.with_name(
            f".{self.selection_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.selection_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.describe()
