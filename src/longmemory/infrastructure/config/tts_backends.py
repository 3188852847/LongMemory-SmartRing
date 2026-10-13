"""圆屏 TTS 下次启动选择；只持久化非敏感后端指针。"""

from __future__ import annotations

import json
import os
from pathlib import Path


BACKENDS = {
    "edge": {"label": "EdgeTTS（联网稳定回退）", "local_service": False,
             "description": "资源占用低，需要联网；当前是整段音频缓冲。"},
    "voxcpm2": {"label": "VoxCPM2（本地参考音色）", "local_service": True,
                "description": "可使用参考 WAV 和表达指令，但首声慢且占用显存。"},
    "sanotts": {"label": "sanoTTS（实验速度基线，音质较低）", "local_service": True,
                "description": "本地 Node/WASM 快速基线，资源较轻；音质较低且当前只有小雅音色。"},
    "cosyvoice3": {"label": "CosyVoice 3（本地高质量，日常推荐）", "local_service": True,
                   "description": "V1 日常声音；本地 0.5B 模型常驻预热并向圆屏分块交付。"},
}


class TTSBackendStore:
    def __init__(self, root: Path, *, current_backend: str = "edge"):
        self.selection_path = Path(root).resolve() / "local/config/preferences/tts-backend.json"
        self.current_backend = self._backend(current_backend)
        self.default_backend = self.current_backend

    @staticmethod
    def _backend(value: str) -> str:
        if value not in BACKENDS:
            raise ValueError("unknown_tts_backend")
        return value

    def selected(self) -> str:
        try:
            body = json.loads(self.selection_path.read_text(encoding="utf-8"))
            value = body.get("selected_backend") if isinstance(body, dict) else None
        except (OSError, ValueError, TypeError):
            value = None
        return value if value in BACKENDS else self.default_backend

    def describe(self, *, voice_running: bool = False) -> dict:
        selected = self.selected()
        return {"current_backend": self.current_backend, "next_start_backend": selected,
                "voice_running": voice_running,
                "restart_required": voice_running and selected != self.current_backend,
                "backends": [{"id": key, **value} for key, value in BACKENDS.items()]}

    def select(self, backend: str, *, voice_running: bool = False) -> dict:
        backend = self._backend(backend)
        body = {"version": 1, "selected_backend": backend}
        self.selection_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.selection_path.with_name(f".{self.selection_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.selection_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.describe(voice_running=voice_running)
