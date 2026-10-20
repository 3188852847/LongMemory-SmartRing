"""固定下载入口的离线 PowerShell/假 curl 测试；从不访问官方 URL。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/development/xiaozhi/Download-SmartTurn.ps1"
SHELLS = [path for name in ("powershell.exe", "pwsh.exe") if (path := shutil.which(name))]
PAYLOAD = b"synthetic SmartTurn model fixture\n"
MODEL = "smart-turn-v3.2-cpu.onnx"
FIXED_URL = ("https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
             "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/" + MODEL)


FAKE_CURL = r'''
import json, os, pathlib, sys
config_path = pathlib.Path(os.environ['AC_FAKE_CURL_CONFIG'])
config = json.loads(config_path.read_text(encoding='utf-8'))
args = sys.argv[1:]
with pathlib.Path(config['calls']).open('a', encoding='utf-8') as log:
    log.write(json.dumps(args) + '\n')
output = pathlib.Path(args[args.index('--output') + 1])
payload = bytes.fromhex(config['payload'])
previous = output.read_bytes() if output.exists() else b''
assert payload.startswith(previous), 'resume must retain existing prefix'
if config.get('stderr'):
    print('synthetic curl progress', file=sys.stderr)
mode = config.get('mode', 'success')
remaining = payload[len(previous):]
if mode == 'partial_failure':
    remaining = remaining[:5]
elif mode == 'corrupt':
    remaining = remaining[:-1] + bytes([remaining[-1] ^ 1])
elif mode == 'short':
    remaining = remaining[:3]
with output.open('ab') as stream:
    stream.write(remaining)
if mode == 'concurrent_destination':
    pathlib.Path(str(output)[:-len('.download')]).write_bytes(b'other owner file')
sys.exit(22 if mode == 'partial_failure' else 0)
'''


def test_production_constants_are_fixed_and_script_is_ps51_utf8_bom():
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")
    source = SCRIPT.read_text(encoding="utf-8-sig")
    assert "#requires -Version 5.1" in source
    assert "$ExpectedBytes = 8679182L" in source
    assert "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f" in source
    assert "4786657e242dfe77dd138699ac564ee074a2a543" in source
    assert "f766f81d3cfdf7737ac64aad813d91bbfd56bf93" in source
    assert "9876" not in source
    assert "Remove-Item" not in source and "--insecure" not in source


@pytest.mark.parametrize("shell", SHELLS, ids=lambda path: Path(path).name)
def test_production_script_parses_offline_in_both_shells(shell):
    path = str(SCRIPT).replace("'", "''")
    command = ("$tokens=$null; $errors=$null; "
               f"[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors) | Out-Null; "
               "[Console]::WriteLine($errors.Count); exit [int]($errors.Count -gt 0)")
    result = subprocess.run([shell, "-NoProfile", "-Command", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    assert result.returncode == 0 and result.stdout.strip() == b"0"


@pytest.fixture(params=SHELLS, ids=lambda path: Path(path).name)
def download_harness(request, tmp_path):
    if os.name != "nt":
        pytest.skip("native Windows shell/cmd fixture")
    directory = tmp_path / "中文 空格"
    directory.mkdir()
    # 仅把临时脚本副本的大小/摘要缩成合成数据；正式入口常量单独精确断言。
    source = SCRIPT.read_text(encoding="utf-8-sig")
    source = source.replace("$ExpectedBytes = 8679182L", f"$ExpectedBytes = {len(PAYLOAD)}L")
    source = source.replace("2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f",
                            hashlib.sha256(PAYLOAD).hexdigest())
    # 仅测试副本保留底层诊断，正式脚本仍输出稳定错误码。
    source = source.replace("$reason = $_.Exception.Message", "[Console]::Error.WriteLine($_.Exception.ToString())\n    $reason = $_.Exception.Message")
    copied = directory / "Download-SmartTurn.ps1"
    copied.write_text(source, encoding="utf-8-sig")
    fake = directory / "fake-curl.py"
    fake.write_text(FAKE_CURL, encoding="utf-8")
    executable = directory / "fake-curl.cmd"
    executable.write_text(f'@echo off\r\n"{sys.executable}" -B "{fake}" %*\r\nexit /b %errorlevel%\r\n', encoding="utf-8")
    config_file, calls = directory / "config.json", directory / "calls.jsonl"
    model_dir = directory / "models"
    model_dir.mkdir()
    config = {"payload": PAYLOAD.hex(), "calls": str(calls)}

    def run(*, mode="success", proxy=None, stderr=False, curl=None):
        config.update(mode=mode, stderr=stderr)
        config_file.write_text(json.dumps(config), encoding="utf-8")
        env = os.environ.copy()
        env["AC_FAKE_CURL_CONFIG"] = str(config_file)
        command = [request.param, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(copied),
                   "-ModelDirectory", str(model_dir), "-CurlPath", str(curl or executable)]
        if proxy is not None:
            command += ["-Proxy", proxy]
        return subprocess.run(command, env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

    def recorded():
        return [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []

    return run, recorded, model_dir / MODEL, model_dir / (MODEL + ".download")


def test_fake_download_verifies_then_renames_without_default_proxy(download_harness):
    run, calls, final, partial = download_harness
    result = run(stderr=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"VERIFIED_SAVED" in result.stdout
    assert final.read_bytes() == PAYLOAD and not partial.exists()
    arguments = calls()[0]
    assert arguments[0] == "-q"
    assert arguments[-1] == FIXED_URL
    assert "--proxy" not in arguments
    assert arguments[arguments.index("--continue-at") + 1] == "-"
    assert arguments[arguments.index("--proto-redir") + 1] == "=https"


def test_partial_failure_preserves_then_resumes_same_file(download_harness):
    run, calls, final, partial = download_harness
    first = run(mode="partial_failure")
    assert first.returncode == 3 and b"CURL_FAILED exit=22" in first.stderr
    assert partial.read_bytes() == PAYLOAD[:5] and not final.exists()
    second = run()
    assert second.returncode == 0
    assert final.read_bytes() == PAYLOAD and not partial.exists()
    assert len(calls()) == 2
    assert all(args[-1] == FIXED_URL for args in calls())


def test_existing_final_only_verifies_and_keeps_old_partial(download_harness):
    run, calls, final, partial = download_harness
    final.write_bytes(PAYLOAD)
    partial.write_bytes(b"keep")
    result = run(curl="does-not-exist.exe")
    assert result.returncode == 0 and b"VERIFIED_EXISTING" in result.stdout, result.stderr.decode(errors="replace")
    assert final.read_bytes() == PAYLOAD and partial.read_bytes() == b"keep"
    assert calls() == []


@pytest.mark.parametrize("value,reason", [(b"short", b"SIZE_MISMATCH"), (b"x" * len(PAYLOAD), b"SHA256_MISMATCH")],
                         ids=["size", "hash"])
def test_bad_final_fails_without_download_or_overwrite(download_harness, value, reason):
    run, calls, final, partial = download_harness
    final.write_bytes(value)
    partial.write_bytes(b"keep")
    result = run()
    assert result.returncode == 1 and reason in result.stderr
    assert final.read_bytes() == value and partial.read_bytes() == b"keep"
    assert calls() == []


def test_complete_valid_partial_promotes_offline_without_curl(download_harness):
    run, calls, final, partial = download_harness
    partial.write_bytes(PAYLOAD)
    assert run(curl="does-not-exist.exe").returncode == 0
    assert final.read_bytes() == PAYLOAD and not partial.exists() and calls() == []


@pytest.mark.parametrize("value,reason", [(b"x" * len(PAYLOAD), b"SHA256_MISMATCH"),
                                         (PAYLOAD + b"extra", b"SIZE_MISMATCH")], ids=["hash", "oversize"])
def test_invalid_complete_partial_is_retained_without_network(download_harness, value, reason):
    run, calls, final, partial = download_harness
    partial.write_bytes(value)
    result = run()
    assert result.returncode == 1 and reason in result.stderr
    assert partial.read_bytes() == value and not final.exists() and calls() == []


@pytest.mark.parametrize("mode,reason", [("corrupt", b"SHA256_MISMATCH"), ("short", b"SIZE_MISMATCH")])
def test_success_exit_cannot_bypass_size_or_sha_validation(download_harness, mode, reason):
    run, _, final, partial = download_harness
    result = run(mode=mode)
    assert result.returncode == 1 and reason in result.stderr
    assert partial.exists() and not final.exists()


def test_explicit_proxy_is_single_native_argument(download_harness):
    run, calls, _, _ = download_harness
    proxy = "http://127.0.0.1:19991"
    assert run(proxy=proxy).returncode == 0
    arguments = calls()[0]
    assert arguments[arguments.index("--proxy") + 1] == proxy


def test_bad_proxy_fails_without_curl_or_partial(download_harness):
    run, calls, final, partial = download_harness
    result = run(proxy="ftp://example.invalid")
    assert result.returncode == 1 and b"INVALID_PROXY" in result.stderr
    assert calls() == [] and not final.exists() and not partial.exists()


def test_missing_curl_fails_before_download(download_harness):
    run, calls, final, partial = download_harness
    result = run(curl="does-not-exist.exe")
    assert result.returncode == 1 and b"CURL_NOT_FOUND" in result.stderr
    assert calls() == [] and not final.exists() and not partial.exists()


def test_destination_created_during_download_is_not_overwritten(download_harness):
    run, _, final, partial = download_harness
    result = run(mode="concurrent_destination")
    assert result.returncode == 1 and b"IO_FAILED" in result.stderr
    assert final.read_bytes() == b"other owner file" and partial.read_bytes() == PAYLOAD


@pytest.mark.parametrize("target_name", ["formal", "partial"])
def test_directory_in_place_of_file_is_retained_and_rejected(download_harness, target_name):
    run, calls, final, partial = download_harness
    target = final if target_name == "formal" else partial
    target.mkdir()
    result = run()
    assert result.returncode == 1 and b"UNSUPPORTED_TARGET" in result.stderr
    assert target.is_dir() and calls() == []
