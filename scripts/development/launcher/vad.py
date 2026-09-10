"""通过小智自己的 Python 安全同步 VAD 档位。"""

import json
from pathlib import Path
import subprocess


def config_action(server: Path, project: Path, profile: str, *, apply=False,
                  expected_digest=None):
    python = server / ".venv/Scripts/python.exe"
    script = project / "scripts/development/xiaozhi/sync_vad_config.py"
    if not python.is_file() or not script.is_file():
        raise ValueError("缺少小智 Python 或 VAD 同步脚本。")
    body = {"action": "apply" if apply else "check", "profile": profile}
    if expected_digest is not None:
        body["expected_digest"] = expected_digest
    result = subprocess.run(
        [str(python), str(script), str(server.resolve())],
        input=json.dumps(body).encode(), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=15, check=False,
    )
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError):
        value = {}
    if result.returncode or value.get("error"):
        raise ValueError("VAD 配置检查或同步失败。")
    return value
