"""在真正的 PowerShell 子进程里检查代理作用域、失败清理和安装参数。

安装阶段及代理都用合成替身；不得调用真实安装、代理或模型下载。
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell only")


def quoted(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.mark.parametrize("fails", [True, False])
@pytest.mark.parametrize("mode", ["-Resume", "-DownloadOnly", "-Stages Tools", "-Stages Models", ""])
def test_wrapper_restores_proxy_and_stops_after_failure(tmp_path, fails, mode):
    wrapper = tmp_path / "run_voice_restore.ps1"
    shutil.copyfile(ROOT / "scripts/development/run_voice_restore.ps1", wrapper)
    proxy = tmp_path / "proxy.ps1"
    proxy.write_text("""
function Enable-DevProxy {
    $script:priorVoiceMarker = $env:VOICE_TEST_MARKER
    $env:VOICE_TEST_MARKER = 'enabled'
    Add-Content -LiteralPath $env:VOICE_TEST_LOG -Value 'enabled'
}
function Disable-DevProxy {
    $env:VOICE_TEST_MARKER = $script:priorVoiceMarker
    Add-Content -LiteralPath $env:VOICE_TEST_LOG -Value 'disabled'
}
""", encoding="utf-8-sig")
    (tmp_path / "restore_voice.ps1").write_text("""
param([string]$Stage)
Add-Content -LiteralPath $env:VOICE_TEST_LOG -Value $Stage
if ($env:VOICE_TEST_FAIL -eq '1' -and $Stage -eq $env:VOICE_TEST_FAIL_STAGE) {
    throw 'synthetic_failure'
}
""", encoding="utf-8-sig")
    log = tmp_path / "stages.txt"
    environment = dict(os.environ, VOICE_TEST_MARKER="original", VOICE_TEST_LOG=str(log),
                       VOICE_TEST_FAIL="1" if fails else "0",
                       VOICE_TEST_FAIL_STAGE=("Tools" if mode == "-Stages Tools" else "Models"
                                             if mode in ("-DownloadOnly", "-Stages Models") else "Environments"))
    command = f"try {{ & {quoted(wrapper)} -ProxyScript {quoted(proxy)} {mode} }} catch {{}}; Write-Output $env:VOICE_TEST_MARKER"
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                            env=environment, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "original"
    stages = log.read_text(encoding="utf-8-sig").splitlines()
    stages_requested = {"": ["Sources", "Environments", "Models", "Tools"],
                        "-Resume": ["Environments", "Models", "Tools"],
                        "-DownloadOnly": ["Models", "Tools"],
                        "-Stages Tools": ["Tools"], "-Stages Models": ["Models"]}[mode]
    expected = ["enabled"]
    if not fails:
        expected += stages_requested
    else:
        end = stages_requested.index(environment["VOICE_TEST_FAIL_STAGE"])
        expected += stages_requested[:end + 1]
    assert stages == expected + ["disabled"]


def test_cosy_install_passes_build_constraints_to_uv(tmp_path):
    script = ROOT / "scripts/development/restore_voice.ps1"
    declarations = ROOT / "scripts/development/voice_restore"
    output = tmp_path / "arguments.json"
    command = f"""
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile({quoted(script)}, [ref]$tokens, [ref]$errors)
$cosyPython = 'synthetic-python'
$voiceDeclarations = {quoted(declarations)}
function Invoke-VoiceCommand {{ param([string]$Command, [string[]]$ArgumentList); $ArgumentList | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath {quoted(output)} }}
$install = $ast.FindAll({{ param($node) $node -is [System.Management.Automation.Language.CommandAst] -and $node.Extent.Text.Contains("'--build-constraints'") }}, $true)
if ($install.Count -ne 1) {{ throw 'constraint command missing or ambiguous' }}
Invoke-Expression $install[0].Extent.Text
"""
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    arguments = json.loads(output.read_text(encoding="utf-8-sig"))
    constraint = Path(arguments[arguments.index("--build-constraints") + 1])
    assert constraint == declarations / "cosyvoice.build.txt"
    assert "setuptools==80.10.2" in constraint.read_text(encoding="utf-8")
    assert "--no-build-isolation" not in arguments
