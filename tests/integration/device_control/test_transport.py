"""本机外部解释器集成验证；环境缺失时明确跳过，不冒充已验证。"""

from pathlib import Path
import os
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = ROOT / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
PYTHON = UPSTREAM / ".venv/Scripts/python.exe"


@pytest.mark.skipif(not PYTHON.is_file(), reason="需要本机已安装的小智 Python 3.10 环境")
def test_real_http_and_upstream_mcp_with_simulated_device(tmp_path):
    # 外部 3.10 进程的 TemporaryDirectory 也归本次 pytest 所有，避免散落到用户临时目录。
    environment = os.environ.copy()
    environment.update(TEMP=str(tmp_path), TMP=str(tmp_path), PYTHONUTF8="1")
    result = subprocess.run([str(PYTHON), str(Path(__file__).with_name("transport_probe.py")),
                             str(UPSTREAM)], capture_output=True, text=True, encoding="utf-8",
                             env=environment, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: independent CLI" in result.stdout
