"""用 Node 内置测试器验证 sanoTTS HTTP 边界；不加载外部模型。"""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_sanotts_node_service_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [node, "--test", str(root / "scripts/development/sanotts/service.test.mjs")],
        cwd=root,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, "sanoTTS Node service contract failed"
