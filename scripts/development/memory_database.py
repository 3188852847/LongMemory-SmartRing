"""检查或显式升级 LongMemory SQLite；绝不接受目录和不存在的路径。"""

import argparse
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from longmemory.infrastructure.database.schema import SCHEMA_VERSION, initialize_schema


def _open_existing(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("数据库文件不存在；本工具不会创建空库。")
    mode = "rw" if writable else "ro"
    connection = sqlite3.connect(resolved.as_uri() + "?mode=" + mode, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if not writable:
        connection.execute("PRAGMA query_only = ON")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        connection.close()
        raise ValueError("数据库 quick_check 未通过，拒绝升级。")
    return connection


def status(path: Path) -> dict:
    connection = _open_existing(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        return {"path": str(path.resolve()), "version": version,
                "target_version": SCHEMA_VERSION, "needs_migration": version != SCHEMA_VERSION}
    finally:
        connection.close()


def migrate(path: Path, backup_directory: Path) -> dict:
    source = _open_existing(path, writable=True)
    backup = None
    try:
        old_version = source.execute("PRAGMA user_version").fetchone()[0]
        if old_version == SCHEMA_VERSION:
            return {"changed": False, "version": old_version, "backup": None}
        if old_version < 1 or old_version > SCHEMA_VERSION:
            raise ValueError(f"不支持从数据库版本 {old_version} 升级。")

        backup_directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = backup_directory.resolve() / f"{path.stem}-pre-v{SCHEMA_VERSION}-{stamp}.db"
        if backup.exists():
            raise ValueError("备份目标意外存在，拒绝覆盖。")
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()

        initialize_schema(source)
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("升级后的数据库 quick_check 未通过；请停止使用并保留备份。")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("升级后的数据库外键校验未通过；请停止使用并保留备份。")
        digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        return {"changed": True, "from_version": old_version,
                "version": SCHEMA_VERSION, "backup": str(backup), "backup_sha256": digest}
    except BaseException:
        source.rollback()
        raise
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="检查或显式升级 LongMemory SQLite")
    parser.add_argument("action", choices=("status", "migrate"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup-directory", type=Path, default=Path("data/backups"))
    parser.add_argument("--confirm-upgrade", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "status":
            result = status(args.database)
        else:
            if not args.confirm_upgrade:
                parser.error("migrate 必须显式添加 --confirm-upgrade；升级前会创建 SQLite 一致性备份")
            result = migrate(args.database, args.backup_directory)
    except (ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
