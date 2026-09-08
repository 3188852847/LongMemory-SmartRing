"""启动前检查/同步圆屏记忆后端；不接触任何后端的记忆数据。"""

import json
from pathlib import Path
import subprocess


BACKENDS = {"longmemory", "xiaozhi_local", "none"}


def config_action(server: Path, project: Path, backend: str, *, apply=False,
                  expected_digest=None):
    if backend not in BACKENDS:
        raise ValueError("未知圆屏记忆后端。")
    python = server / ".venv/Scripts/python.exe"
    script = project / "scripts/development/xiaozhi/sync_memory_config.py"
    if not python.is_file() or not script.is_file():
        raise ValueError("小智环境或记忆后端同步工具不完整。")
    command = [str(python), str(script), "--server", str(server),
               "--profile", backend, "--action", "apply" if apply else "check"]
    if apply:
        command.extend(["--expected-digest", str(expected_digest or "")])
    try:
        result = subprocess.run(command, capture_output=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("圆屏记忆配置检查超时或无法运行；不要假定配置未写入。") from None
    if result.returncode or not result.stdout or len(result.stdout) > 4096:
        raise ValueError("圆屏记忆配置检查失败；未读取或修改记忆数据。")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("圆屏记忆配置返回格式异常。") from None
