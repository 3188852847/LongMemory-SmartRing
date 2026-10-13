"""固件恢复的身份、路径与补丁边界；合成数据不访问设备或网络。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile

import pytest

DIRECTORY = Path(__file__).resolve().parents[3] / "scripts/development/firmware_restore"
SPEC = importlib.util.spec_from_file_location("firmware_restore_check", DIRECTORY / "check_sources.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)
ARTIFACT_SPEC = importlib.util.spec_from_file_location("firmware_artifacts_check", DIRECTORY / "check_artifacts.py")
artifacts = importlib.util.module_from_spec(ARTIFACT_SPEC)
ARTIFACT_SPEC.loader.exec_module(artifacts)


def test_fingerprints_accept_exact_bytes(tmp_path):
    (tmp_path / "board.cc").write_bytes(b"fixed source\n")
    wanted = {"board.cc": hashlib.sha256(b"fixed source\n").hexdigest()}
    assert check.validate_fingerprints(tmp_path, wanted) == wanted


def test_fingerprints_reject_same_name_changed_content(tmp_path):
    (tmp_path / "board.cc").write_bytes(b"new upstream\n")
    with pytest.raises(ValueError, match="摘要不一致"):
        check.validate_fingerprints(tmp_path, {"board.cc": hashlib.sha256(b"old source\n").hexdigest()})


def test_fingerprints_reject_missing_file(tmp_path):
    with pytest.raises(ValueError, match="缺失"):
        check.validate_fingerprints(tmp_path, {"board.cc": "0" * 64})


def test_fingerprints_reject_parent_traversal(tmp_path):
    with pytest.raises(ValueError, match="相对路径无效"):
        check.validate_fingerprints(tmp_path, {"../external": "0" * 64})


def test_checkout_rejects_local_changes(monkeypatch, tmp_path):
    def git(directory, *args):
        return "fixed" if args[0] == "rev-parse" else " M board.cc"
    monkeypatch.setattr(check, "git_output", git)
    with pytest.raises(ValueError, match="本地改动"):
        check.validate_checkout(tmp_path, "fixed")


def test_checkout_rejects_different_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "git_output", lambda *args: "different")
    with pytest.raises(ValueError, match="固定提交"):
        check.validate_checkout(tmp_path, "fixed")


@pytest.mark.parametrize("prefix", ["-", "+", "U"])
def test_sdk_rejects_incomplete_or_changed_submodules(monkeypatch, tmp_path, prefix):
    monkeypatch.setattr(check, "validate_checkout", lambda *args: None)
    monkeypatch.setattr(check, "git_output", lambda *args: prefix + "a" * 40 + " components/module")
    with pytest.raises(ValueError, match="子模块"):
        check.check_sdk(tmp_path)


def test_sdk_rejects_unexpected_official_tool_version(monkeypatch, tmp_path):
    monkeypatch.setattr(check, "validate_checkout", lambda *args: None)
    monkeypatch.setattr(check, "git_output", lambda *args: " " + "a" * 40 + " components/module")
    (tmp_path / "tools").mkdir()
    tools = {"tools": [{"name": "cmake", "versions": [{"name": "4.4.4", "status": "recommended"}]}]}
    (tmp_path / "tools/tools.json").write_text(json.dumps(tools))
    with pytest.raises(ValueError, match="工具清单"):
        check.check_sdk(tmp_path)


def test_preparing_worktree_never_overwrites_existing_source(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(DIRECTORY))
    import prepare_worktree
    monkeypatch.setattr(prepare_worktree, "check_vendor", lambda *args: {"project": str(tmp_path)})
    (tmp_path / "src").mkdir()
    (tmp_path / "src/my-change.cc").write_text("my work")
    with pytest.raises(FileExistsError, match="未覆盖"):
        prepare_worktree.prepare(tmp_path, tmp_path)
    assert (tmp_path / "src/my-change.cc").read_text() == "my work"


def test_cumulative_patch_has_valid_fixed_receipt():
    folder = DIRECTORY.parents[2] / "firmware/smartring_plus/restore"
    metadata = json.loads((folder / "overlay.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((folder / "restore-0012.patch").read_bytes()).hexdigest() == metadata["patch_sha256"]
    assert metadata["basis_commit"] == check.MANIFEST["vendor"]["commit"]


def partition_binary(entries):
    content = b"".join(struct.pack("<HBBII16sI", 0x50AA, kind, subtype, start, size,
                                   label.encode(), 0) for label,kind,subtype,start,size in entries)
    return content + b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(content).digest()


def test_partition_table_uses_compiled_offsets():
    data = partition_binary([("ota_0",0,0x10,0x20000,0x3F0000),
                             ("ota_1",0,0x11,0x410000,0x3F0000),
                             ("assets",1,0x82,0x800000,0x200000)])
    parsed = artifacts.parse_partitions(data)
    assert parsed["ota_1"]["offset"] == 0x410000
    assert parsed["assets"]["size"] == 0x200000


def test_partition_table_rejects_corrupted_checksum():
    data = bytearray(partition_binary([("ota_0",0,0x10,0x20000,0x3F0000)]))
    data[-1] ^= 1
    with pytest.raises(ValueError, match="MD5"):
        artifacts.parse_partitions(bytes(data))


def test_partition_table_rejects_overlap():
    data = partition_binary([("ota_0",0,0x10,0x20000,0x3F0000),
                             ("assets",1,0x82,0x300000,0x200000)])
    with pytest.raises(ValueError, match="重叠"):
        artifacts.parse_partitions(data)


def test_artifacts_reject_oversized_application_without_receipt(tmp_path):
    (tmp_path / "project_description.json").write_text(json.dumps({"target":"esp32s3","project_name":"xiaozhi"}))
    for name in artifacts.REQUIRED:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    partition = partition_binary([("ota_0",0,0x10,0x20000,32), ("assets",1,0x82,0x800000,128)])
    (tmp_path / "partition_table/partition-table.bin").write_bytes(partition)
    header = bytearray(64);header[0] = 0xE9;struct.pack_into("<H",header,12,9)
    (tmp_path / "xiaozhi.bin").write_bytes(header)
    (tmp_path / "bootloader/bootloader.bin").write_bytes(header)
    (tmp_path / "xiaozhi.elf").write_bytes(b"\x7fELF-fixture")
    with pytest.raises(ValueError, match="超过应用分区"):
        artifacts.check(tmp_path)
    assert not (tmp_path / "restore-build.json").exists()


def _windows_short_path(path):
    """向 Windows 查询真实 8.3 别名；无别名的卷会返回原路径。"""
    import ctypes
    from ctypes import wintypes
    function = ctypes.windll.kernel32.GetShortPathNameW
    function.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    function.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(str(path), buffer, len(buffer))
    assert 0 < length < len(buffer), "合成文件必须存在且能够查询 Windows 路径"
    return buffer.value


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell registry integration")
@pytest.mark.parametrize("path_form", ["long", "short_root", "short_root_and_sdk"])
def test_registry_merges_completed_sdk_without_switching_original_default(path_form):
    with tempfile.TemporaryDirectory(prefix="smart-ring-registry-check-") as directory:
        root = Path(directory)
        sdk = root / "v5.5.4/esp-idf"
        python = root / "python_env/v5.5.4/venv/Scripts/python.exe"
        profile = root / "Microsoft.v5.5.4.PowerShell_profile.ps1"
        sdk.mkdir(parents=True)
        python.parent.mkdir(parents=True)
        python.touch()
        profile.touch()
        (root / "tools").mkdir()
        prior = {"idfInstalled":[{"id":"original","path":str(root / "v6.1/esp-idf"),"name":"v6.1"}],
                 "idfSelectedId":"original","version":"3.0"}
        original = root / "prior.json"
        original.write_text(json.dumps(prior),encoding="utf-8")
        vendor = root / "vendor.json"
        record = {"id":"new","path":str(sdk),"python":str(python),"activationScript":str(profile),"status":"finished"}
        vendor.write_text(json.dumps({"idfInstalled":[record]}),encoding="utf-8")
        (root / "tools/eim_idf.json").write_text(json.dumps(prior),encoding="utf-8")
        esp_root = _windows_short_path(root) if path_form != "long" else str(root)
        sdk_path = _windows_short_path(sdk) if path_form == "short_root_and_sdk" else str(sdk)
        result = subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",
                                 str(DIRECTORY / "sync_registry.ps1"),"-EspRoot",esp_root,"-SdkPath",sdk_path,
                                 "-PriorRegistry",str(original),"-VendorRegistry",str(vendor)],
                                capture_output=True,timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        merged = json.loads((root / "tools/eim_idf.json").read_text(encoding="utf-8-sig"))
        assert merged["idfSelectedId"] == "original"
        assert merged["idfInstalled"] == prior["idfInstalled"] + [record]


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="Windows PowerShell registry integration")
@pytest.mark.parametrize("invalid_path", ["missing_python", "missing_profile", "sibling_python"])
def test_registry_short_root_still_rejects_missing_or_outside_paths(invalid_path):
    with tempfile.TemporaryDirectory(prefix="smart-ring-registry-boundary-") as directory:
        root = Path(directory) / "esp"
        sdk = root / "v5.5.4/esp-idf"
        python = root / "python_env/v5.5.4/venv/Scripts/python.exe"
        profile = root / "Microsoft.v5.5.4.PowerShell_profile.ps1"
        sdk.mkdir(parents=True)
        python.parent.mkdir(parents=True)
        python.touch()
        profile.touch()
        if invalid_path == "missing_python":
            python.unlink()
        elif invalid_path == "missing_profile":
            profile.unlink()
        else:
            # esp-sibling 与 esp 共享字符串前缀，仍然属于根目录外；
            # 文件真实存在，不能仅靠缺失文件检测碰巧拒绝越界。
            python = Path(directory) / "esp-sibling/python.exe"
            python.parent.mkdir()
            python.touch()
        (root / "tools").mkdir()
        prior = {"idfInstalled": [], "idfSelectedId": "original", "version": "3.0"}
        original = root / "prior.json"
        original.write_text(json.dumps(prior), encoding="utf-8")
        destination = root / "tools/eim_idf.json"
        destination.write_text(json.dumps(prior), encoding="utf-8")
        before = destination.read_bytes()
        vendor = root / "vendor.json"
        record = {"id": "new", "path": str(sdk), "python": str(python),
                  "activationScript": str(profile), "status": "finished"}
        vendor.write_text(json.dumps({"idfInstalled": [record]}), encoding="utf-8")
        result = subprocess.run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(DIRECTORY / "sync_registry.ps1"), "-EspRoot", _windows_short_path(root),
            "-SdkPath", str(sdk), "-PriorRegistry", str(original), "-VendorRegistry", str(vendor),
        ], capture_output=True, timeout=30)
        assert result.returncode != 0
        assert destination.read_bytes() == before
        assert not (root / "tools/eim_idf.json.smart-ring.tmp").exists()


@pytest.mark.skipif(not shutil.which("powershell.exe") or not shutil.which("uv"), reason="Windows SDK preparation failure cleanup")
def test_installer_restores_proxy_and_sdk_environment_after_early_failure():
    with tempfile.TemporaryDirectory(prefix="smart-ring-environment-check-") as directory:
        root = Path(directory)
        if not str(root).isascii() or " " in str(root):
            pytest.skip("Integration fixture needs an ASCII no-space path")
        # 提前失败必须从代理开启后的空 EIM 分支触发，不能碰巧因当前检出
        # 缺少 .venv 而在代理之前退出。只复制入口与清单到一次性合成项目；
        # Python 占位不会执行（不存在的 EIM 先使 SDK 阶段失败）。
        development = root / "synthetic-project/scripts/development"
        (development / "firmware_restore").mkdir(parents=True)
        wrapper = development / "run_firmware_restore.ps1"
        shutil.copyfile(DIRECTORY.parent / "run_firmware_restore.ps1", wrapper)
        shutil.copyfile(DIRECTORY / "manifest.json", development / "firmware_restore/manifest.json")
        python_placeholder = root / "synthetic-project/.venv/Scripts/python.exe"
        python_placeholder.parent.mkdir(parents=True)
        python_placeholder.touch()
        marker = root / "proxy.log"
        proxy = root / "proxy.ps1"
        def literal(value):
            return "'" + str(value).replace("'", "''") + "'"
        proxy.write_text(
            "function Enable-DevProxy { [IO.File]::AppendAllText(" + literal(marker) + ", 'enable,'); $env:IDF_PATH='temporary-value' }\n"
            "function Disable-DevProxy { [IO.File]::AppendAllText(" + literal(marker) + ", 'disable') }\n", encoding="utf-8-sig")
        harness = root / "check.ps1"
        source = "$ErrorActionPreference='Stop'; $env:IDF_PATH='original-value'; try { & "
        source += literal(wrapper)
        source += " -ProxyScript " + literal(proxy) + " -Stage Sdk -EspRoot " + literal(root / "empty-esp")
        source += " -WorkRoot " + literal(root / "work") + "; exit 2 } catch {"
        source += "if($env:IDF_PATH -ne 'original-value') {exit 3}; if([IO.File]::ReadAllText("
        source += literal(marker) + ") -ne 'enable,disable') {exit 4}; exit 0 }"
        harness.write_text(source, encoding="utf-8-sig")
        result = subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(harness)],
                                capture_output=True,timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
