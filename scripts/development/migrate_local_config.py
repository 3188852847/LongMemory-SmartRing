"""可回退的本机配置迁移；默认只预检，不输出配置内容。

只有停止旧启动器与服务后才能 apply。外部依赖、数据库和设备不在迁移范围。
文件不重写，env/偏好原子移动；小智配置复制为 canonical 并保留厂家消费副本。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os
import sys
import uuid

ENV_NAMES = (".env", ".env.deepseek.local", ".env.web-search.local", ".env.doubao.local")
PREFERENCE_NAMES = ("launcher.json", "model-profile.json", "memory-backend.json", "tts-backend.json")
DISPLAY_NAMES = ("round-skin-selection.json", "round-skin-custom.skin.json")
SERVER = "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
PAIRS = tuple((name, "local/config/" + name, "move") for name in ENV_NAMES) + tuple(
    ("data/control/" + name, "local/config/preferences/" + name, "move") for name in PREFERENCE_NAMES
) + tuple(("data/control/" + name, "local/config/display/" + name, "move") for name in DISPLAY_NAMES) + (
    (SERVER + "/data/.config.yaml", "local/config/xiaozhi.yaml", "copy"),
)


def safe_path(root, relative):
    root = Path(root).absolute()
    path = root / relative
    try:
        path.absolute().relative_to(root)
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("unsafe_migration_path") from None
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink() or (part.exists() and getattr(part.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("unsafe_migration_path")
    return path


def digest(path):
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("invalid_config_file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(root):
    entries = []
    for source_name, target_name, mode in PAIRS:
        source = safe_path(root, source_name)
        target = safe_path(root, target_name)
        if source.exists() and target.exists():
            if mode == "copy" and digest(source) == digest(target):
                continue
            raise ValueError("migration_destination_exists")
        if source.exists():
            entries.append({"source": source_name, "target": target_name, "mode": mode, "sha256": digest(source)})
        elif target.exists():
            digest(target)  # 重复运行时只确认现有 canonical 为普通小文件，不改它。
    return entries


def _write_receipt(path, body):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(root, *, services_stopped=False):
    if not services_stopped:
        raise ValueError("services_must_be_stopped")
    root = Path(root).absolute()
    entries = plan(root)
    receipt = safe_path(root, "local/archive/config-migrations/" + uuid.uuid4().hex + ".json")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": 1, "state": "prepared", "entries": entries, "completed": [], "pending": None}
    _write_receipt(receipt, body)
    try:
        for entry in entries:
            source = safe_path(root, entry["source"])
            target = safe_path(root, entry["target"])
            if digest(source) != entry["sha256"] or target.exists():
                raise ValueError("config_changed_before_migration")
            # 先写意图；即使在 rename 后进程终止，也能从 pending 核对并回退。
            body["pending"] = entry
            _write_receipt(receipt, body)
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["mode"] == "move":
                source.rename(target)
            else:
                temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".migration-part")
                try:
                    with temporary.open("xb") as handle:
                        handle.write(source.read_bytes())
                        handle.flush()
                        os.fsync(handle.fileno())
                    if digest(temporary) != entry["sha256"] or digest(source) != entry["sha256"]:
                        raise ValueError("config_changed_before_migration")
                    temporary.rename(target)
                finally:
                    if temporary.exists():
                        # 保存失败的中间字节；不把半成品留在 canonical 入口。
                        temporary.rename(receipt.parent / (receipt.stem + "-partial-" + uuid.uuid4().hex))
            body["completed"].append(entry)
            body["pending"] = None
            _write_receipt(receipt, body)
            if digest(target) != entry["sha256"]:
                raise ValueError("migration_hash_mismatch")
        body["state"] = "complete"
        _write_receipt(receipt, body)
    except Exception:
        # 只撤销本事务已经完成、且摘要仍相同的文件；不覆盖并发编辑。
        try:
            rollback(root, receipt, _body=body)
        except Exception:
            body["state"] = "rollback_required"
            _write_receipt(receipt, body)
        raise
    return {"migrated": len(entries), "receipt": receipt.relative_to(root).as_posix()}


def rollback(root, receipt, *, _body=None):
    root = Path(root).absolute()
    receipt = safe_path(root, Path(receipt).absolute().relative_to(root))
    receipt.relative_to(root / "local/archive/config-migrations")
    body = _body if _body is not None else json.loads(receipt.read_text(encoding="utf-8"))
    if body.get("version") != 1 or body.get("state") == "rolled_back":
        raise ValueError("invalid_migration_receipt")
    completed = list(body.get("completed", []))
    pending = body.get("pending")
    if pending is not None and pending not in completed:
        if (pending["source"], pending["target"], pending["mode"]) not in set(PAIRS):
            raise ValueError("invalid_migration_receipt")
        if safe_path(root, pending["target"]).exists():
            completed.append(pending)
    allowed = set(PAIRS)
    for entry in completed:
        if (entry["source"], entry["target"], entry["mode"]) not in allowed:
            raise ValueError("invalid_migration_receipt")
        source, target = (safe_path(root, entry[key]) for key in ("source", "target"))
        if digest(target) != entry["sha256"]:
            raise ValueError("canonical_config_changed")
        if entry["mode"] == "move" and source.exists():
            raise ValueError("rollback_destination_exists")
        if entry["mode"] == "copy" and digest(source) != entry["sha256"]:
            raise ValueError("runtime_config_changed")
        if entry["mode"] == "copy" and (receipt.parent / (receipt.stem + "-xiaozhi.yaml")).exists():
            raise ValueError("rollback_archive_exists")
    for entry in reversed(completed):
        source, target = (safe_path(root, entry[key]) for key in ("source", "target"))
        if entry["mode"] == "move":
            source.parent.mkdir(parents=True, exist_ok=True)
            target.rename(source)
        else:
            # 仅移走本事务新增的副本，保留可恢复内容，不清空配置资产。
            archive = receipt.parent / (receipt.stem + "-xiaozhi.yaml")
            if archive.exists():
                raise ValueError("rollback_archive_exists")
            target.rename(archive)
    body["state"] = "rolled_back"
    body["pending"] = None
    _write_receipt(receipt, body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            if not args.services_stopped:
                raise ValueError("services_must_be_stopped")
            rollback(args.project, args.rollback)
            result = {"rolled_back": True}
        elif args.apply:
            result = apply(args.project, services_stopped=args.services_stopped)
        else:
            result = {"planned": plan(args.project)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        # 固定错误码不包含文件原文、第三方 traceback 或系统异常文本。
        codes = {"unsafe_migration_path", "invalid_config_file", "migration_destination_exists",
                 "services_must_be_stopped", "config_changed_before_migration", "migration_hash_mismatch",
                 "invalid_migration_receipt", "canonical_config_changed", "rollback_destination_exists",
                 "runtime_config_changed", "rollback_archive_exists"}
        code = str(error) if isinstance(error, ValueError) and str(error) in codes else "config_migration_failed"
        print(json.dumps({"error": code}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
