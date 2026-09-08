"""启动前检查/同步圆屏模型；只接收具名档案，不传递或输出密钥。"""

import json
from pathlib import Path
import subprocess


def config_action(server: Path, project: Path, profile: str, *, apply=False,
                  expected_digest=None):
    if profile not in {"campus", "official"}:
        raise ValueError("未知圆屏模型配置档。")
    python = server / ".venv/Scripts/python.exe"
    script = project / "scripts/development/xiaozhi/sync_model_config.py"
    env_file = project / ({"campus": ".env", "official": ".env.deepseek.local"}[profile])
    if not python.is_file() or not script.is_file() or not env_file.is_file():
        raise ValueError("小智环境、模型同步工具或所选本机配置档不完整。")
    command = [str(python), str(script), "--project", str(project), "--server", str(server),
               "--profile", profile, "--action", "apply" if apply else "check"]
    if apply:
        command.extend(["--expected-digest", str(expected_digest or "")])
    try:
        result = subprocess.run(command, capture_output=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("圆屏模型配置检查超时或无法运行；不要假定配置未写入。") from None
    if result.returncode or not result.stdout or len(result.stdout) > 4096:
        raise ValueError("圆屏模型配置检查失败；请核对所选档案、小智目录和私有 YAML。")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("圆屏模型配置返回格式异常。") from None
