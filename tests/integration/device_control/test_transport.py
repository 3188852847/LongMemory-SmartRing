"""本机外部解释器集成验证；环境缺失时明确跳过，不冒充已验证。"""

from pathlib import Path
import subprocess

import pytest


UPSTREAM = Path(r"D:\ESP32-Workspace\xiaozhi-esp32-server\main\xiaozhi-server")
PYTHON = UPSTREAM / ".venv/Scripts/python.exe"


@pytest.mark.skipif(not PYTHON.is_file(), reason="需要本机已安装的小智 Python 3.10 环境")
def test_real_http_and_upstream_mcp_with_simulated_device():
    result = subprocess.run([str(PYTHON), str(Path(__file__).with_name("transport_probe.py")),
                             str(UPSTREAM)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: independent CLI" in result.stdout
