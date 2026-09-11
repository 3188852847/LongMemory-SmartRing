"""从启动面板检查或显式切换小智 TTS；不读取、记录或输出私有配置。"""

import json
from pathlib import Path
import subprocess


def config_action(server: Path, project: Path, backend: str, *, apply=False, expected_digest=None):
    if backend not in {"edge", "voxcpm2", "sanotts"}:
        raise ValueError("未知语音后端。")
    python = server / ".venv/Scripts/python.exe"
    script = project / "scripts/development/xiaozhi/sync_tts_backend.py"
    if not python.is_file() or not script.is_file() or not (server / "app.py").is_file():
        raise ValueError("小智环境或 TTS 同步工具不完整。")
    body = {"action": "apply" if apply else "check", "backend": backend}
    if apply:
        body["expected_digest"] = expected_digest
    try:
        result = subprocess.run(
            [str(python), str(script), str(server)],
            input=json.dumps(body).encode("utf-8"), capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("TTS 配置检查超时或无法运行；不要假定配置未写入。") from None
    if result.returncode or not result.stdout or len(result.stdout) > 4096:
        raise ValueError("TTS 配置检查/同步失败；未显示私有配置内容。")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("TTS 配置返回格式异常。") from None
