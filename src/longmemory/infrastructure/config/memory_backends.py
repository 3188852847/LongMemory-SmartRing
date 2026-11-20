"""日用记忆固定使用 Hy，状态页仍如实报告当前服务的引擎。"""


class MemoryBackendStore:
    def __init__(self, *, current_backend: str):
        self.current_backend = current_backend

    def selected(self):
        return "hy_memory"

    def describe(self):
        return {
            "current_backend": self.current_backend,
            "next_start_backend": self.selected(),
            "restart_required": self.current_backend != self.selected(),
            "backends": [{"id": "hy_memory", "label": "Hy-Memory", "provider": "LongMemory",
                          "description": "网页和圆屏共享长期记忆。", "persistent": True}],
        }
