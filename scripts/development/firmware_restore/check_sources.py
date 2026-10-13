"""只读核对全新固件源码及 SDK；不下载、不改源码、不接触设备。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))


def git_output(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments], capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("Git 目录或命令无效；保留中断现场，不自动清理或重置。")
    return result.stdout.decode("utf-8").strip()


def validate_checkout(directory: Path, commit: str) -> None:
    if git_output(directory, "rev-parse", "HEAD") != commit:
        raise ValueError("源码 HEAD 与固定提交不一致；未覆盖或切换现有目录。")
    if git_output(directory, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("源码目录存在本地改动；未覆盖或回退。")


def validate_fingerprints(project: Path, expected: dict[str, str]) -> dict[str, str]:
    actual = {}
    for name, digest in expected.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("摘要清单中的相对路径无效。")
        path = project / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"基线文件缺失或不是普通文件：{name}")
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != digest.lower():
            raise ValueError(f"厂家基线摘要不一致：{name}")
    return actual


def check_sdk(directory: Path) -> dict:
    validate_checkout(directory, MANIFEST["sdk"]["commit"])
    statuses = git_output(directory, "submodule", "status", "--recursive").splitlines()
    # 输出首列分别表示未初始化、提交偏离和冲突；不能把父仓库正确当作 SDK 完整。
    if not statuses or any(line.startswith(("-", "+", "U")) for line in statuses):
        raise ValueError("SDK 子模块未完整初始化或提交不一致。")
    tools = json.loads((directory / "tools/tools.json").read_text(encoding="utf-8"))
    wanted = {"cmake": MANIFEST["sdk"]["cmake_version"],
              "ninja": MANIFEST["sdk"]["ninja_version"],
              "xtensa-esp-elf": MANIFEST["sdk"]["compiler_version"]}
    for name, version in wanted.items():
        entry = next(item for item in tools["tools"] if item["name"] == name)
        if not any(item["name"] == version and item["status"] == "recommended"
                   for item in entry["versions"]):
            raise ValueError(f"SDK 官方工具清单不符合已核实版本：{name}")
    return {"sdk_commit": MANIFEST["sdk"]["commit"], "submodule_count": len(statuses),
            "recommended_tools": wanted, "compiled": False}


def check_vendor(directory: Path) -> dict:
    validate_checkout(directory, MANIFEST["vendor"]["commit"])
    baseline = json.loads((ROOT / "firmware/smartring_plus/upstream-baseline.json").read_text(encoding="utf-8"))
    project = directory / MANIFEST["vendor"]["project_directory"]
    actual = validate_fingerprints(project, baseline["files_sha256"])
    return {"vendor_commit": MANIFEST["vendor"]["commit"], "project": str(project),
            "files_sha256": actual, "overlay_applied": False, "compiled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("sdk", "vendor"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = check_sdk(args.directory) if args.kind == "sdk" else check_vendor(args.directory)
    except (ValueError, OSError, StopIteration) as error:
        parser.exit(1, f"核对失败：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
