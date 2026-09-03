"""确保中文防火墙脚本兼容 Windows PowerShell 5.1；只解析，不执行规则。"""

import codecs
import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/firewall.ps1"


def test_chinese_powershell_script_has_utf8_bom():
    # Windows PowerShell 5.1 对无 BOM 文件可能按本地 ANSI 编码解析，
    # 中文字节可能被误读成引号等语法字符；BOM 明确指定 UTF-8。
    content = SCRIPT.read_bytes()
    assert content.startswith(codecs.BOM_UTF8)
    assert content.decode("utf-8-sig").startswith("# 在管理员 PowerShell")


def test_windows_powershell_51_can_parse_without_running_script():
    executable = (
        Path(os.environ.get("SystemRoot", "C:/Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if os.name != "nt" or not executable.is_file():
        pytest.skip("当前环境没有 Windows PowerShell 5.1")
    # ParseFile 只读取语法树，不执行脚本，因此不需要管理员权限，
    # 也不会创建、撤销防火墙规则或检查真实网络。
    escaped_path = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped_path}', [ref]$tokens, [ref]$errors) > $null; "
        "if ($errors.Count) { $errors | Out-String | Write-Output; exit 1 }"
    )
    result = subprocess.run(
        [str(executable), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
