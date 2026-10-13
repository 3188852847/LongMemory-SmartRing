"""从全新厂家 checkout 创建固件工作副本，只叠加项目补丁和版本记录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from check_sources import ROOT, MANIFEST, check_vendor, validate_fingerprints

RESTORE = ROOT / "firmware/smartring_plus/restore"


def apply_patch(directory: Path, patch: Path, *, check=False, reverse=False) -> None:
    env = os.environ.copy()
    # 工作副本没有主仓库的 Git 元数据。阻止测试目录或外部父目录被发现为仓库，
    # 保证 git apply 始终只处理明确 cwd 的厂家工作副本。
    env["GIT_CEILING_DIRECTORIES"] = str(directory.parent.resolve())
    arguments = ["git", "apply", "--unidiff-zero", "--whitespace=nowarn"]
    if check:
        arguments.append("--check")
    if reverse:
        arguments.append("--reverse")
    result = subprocess.run(arguments + [str(patch.resolve())], cwd=directory,
                            env=env, capture_output=True)
    if result.returncode:
        raise ValueError("累计补丁无法干净应用或反向检查；保留现场，不修改已有工作副本。")


def prepare(vendor: Path, work_root: Path) -> dict:
    target = work_root / "src"
    if target.exists():
        raise FileExistsError("工作副本已存在，未覆盖；请先核对已有恢复回执。")
    if not str(work_root.resolve()).isascii() or any(c in str(work_root) for c in " ()"):
        raise ValueError("实际工作目录必须使用无空格、括号的 ASCII 路径。")
    baseline = check_vendor(vendor)
    metadata = json.loads((RESTORE / "overlay.json").read_text(encoding="utf-8"))
    patch = RESTORE / "restore-0012.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != metadata["patch_sha256"]:
        raise ValueError("累计补丁摘要不符。")
    if metadata["basis_commit"] != MANIFEST["vendor"]["commit"]:
        raise ValueError("累计补丁与厂家固定提交不匹配。")
    source = Path(baseline["project"])
    before = {name: item["before_sha256"] for name, item in metadata["files"].items()}
    after = {name: item["after_sha256"] for name, item in metadata["files"].items()}
    validate_fingerprints(source, before)
    work_root.mkdir(parents=True, exist_ok=True)
    temporary = work_root / ("src-prepare-" + uuid.uuid4().hex[:10])
    temporary.mkdir()
    # 不复制厂家预编译镜像、生成文件、旧构建或依赖缓存；这里只读新 checkout。
    for name in ("main", "partitions", "scripts"):
        shutil.copytree(source / name, temporary / name)
    for name in ("CMakeLists.txt", "LICENSE", ".clang-format"):
        shutil.copyfile(source / name, temporary / name)
    for path in [*source.glob("sdkconfig.defaults*"), *source.glob("README*.md")]:
        shutil.copyfile(path, temporary / path.name)
    apply_patch(temporary, patch, check=True)
    apply_patch(temporary, patch)
    validate_fingerprints(temporary, after)
    apply_patch(temporary, patch, check=True, reverse=True)
    shutil.copyfile(RESTORE / "sdkconfig.restore.defaults", temporary / "sdkconfig.restore.defaults")
    import yaml  # 主项目已有 PyYAML；不为固件混装 SDK 或语音依赖。
    component_metadata = json.loads((RESTORE / "components.json").read_text(encoding="utf-8"))
    lock = component_metadata["lock"]
    if lock.get("target") != MANIFEST["target"]:
        raise ValueError("组件版本记录的芯片目标不符。")
    (temporary / "dependencies.lock").write_text(
        yaml.safe_dump(lock, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    # 锁文件只描述重新取得的版本与摘要，managed_components 尚未存在。
    result = {"schema_version": 1, "vendor_commit": MANIFEST["vendor"]["commit"],
              "target": MANIFEST["target"], "sdk_commit": MANIFEST["sdk"]["commit"],
              "patch_sha256": metadata["patch_sha256"], "source_files_sha256": after,
              "components": "version metadata reconstructed; fresh download pending",
              "compiled": False, "flashed": False}
    (temporary / "restore-source.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    # 失败时临时副本也保留，不删除未知或诊断文件；只有全部核对通过才发布 src。
    temporary.rename(target)
    return dict(result, directory=str(target))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.vendor, args.work_root)
    except (ValueError, OSError) as error:
        parser.exit(1, f"工作副本准备失败：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
