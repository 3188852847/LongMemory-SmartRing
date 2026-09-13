"""检查、升级或验证恢复 LongMemory SQLite；绝不创建未指定的活动库。"""

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_signature(connection: sqlite3.Connection) -> tuple[int, tuple]:
    """只比较结构版本和逐表行数，不读取或输出个人正文。"""

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    table_names = tuple(row[0] for row in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ))
    counts = []
    for name in table_names:
        # 表名来自 sqlite_schema，不接收命令行文本；双引号仍作防御性转义。
        identifier = '"' + name.replace('"', '""') + '"'
        counts.append((name, connection.execute(
            f"SELECT COUNT(*) FROM {identifier}"
        ).fetchone()[0]))
    return version, tuple(counts)


def verify_restore(path: Path, backup_directory: Path) -> dict:
    """一致性备份活动库，再从该备份创建独立恢复副本并比较逻辑签名。"""

    source = _open_existing(path)
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_directory.resolve() / f"{path.stem}-v1-rc-backup-{stamp}.db"
    restored = (
        backup_directory.resolve()
        / f"{path.stem}-v1-rc-restore-check-{stamp}.db"
    )
    if backup.exists() or restored.exists():
        source.close()
        raise ValueError("恢复演练目标意外存在，拒绝覆盖。")
    try:
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("活动数据库外键校验未通过，拒绝创建恢复演练。")
        backup_connection = sqlite3.connect(backup)
        try:
            source.backup(backup_connection)
        finally:
            backup_connection.close()
    finally:
        source.close()

    backup_source = _open_existing(backup)
    try:
        if backup_source.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("一致性备份外键校验未通过。")
        backup_signature = _logical_signature(backup_source)
        restore_destination = sqlite3.connect(restored)
        try:
            backup_source.backup(restore_destination)
        finally:
            restore_destination.close()
    finally:
        backup_source.close()

    restored_source = _open_existing(restored)
    try:
        if restored_source.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("恢复副本外键校验未通过。")
        restored_signature = _logical_signature(restored_source)
    finally:
        restored_source.close()
    if restored_signature != backup_signature:
        raise RuntimeError("恢复副本与一致性备份的结构或逐表行数不一致。")
    version, table_counts = backup_signature
    return {
        "verified": True,
        "version": version,
        "table_count": len(table_counts),
        "total_rows": sum(count for _name, count in table_counts),
        "backup": str(backup),
        "backup_sha256": _sha256(backup),
        "restored_copy": str(restored),
        "restored_sha256": _sha256(restored),
    }


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
    parser = argparse.ArgumentParser(description="检查、升级或验证恢复 LongMemory SQLite")
    parser.add_argument("action", choices=("status", "migrate", "verify-restore"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup-directory", type=Path, default=Path("data/backups"))
    parser.add_argument("--confirm-upgrade", action="store_true")
    parser.add_argument("--confirm-backup", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "status":
            result = status(args.database)
        elif args.action == "migrate":
            if not args.confirm_upgrade:
                parser.error("migrate 必须显式添加 --confirm-upgrade；升级前会创建 SQLite 一致性备份")
            result = migrate(args.database, args.backup_directory)
        else:
            if not args.confirm_backup:
                parser.error(
                    "verify-restore 必须显式添加 --confirm-backup；"
                    "它会创建一致性备份和独立恢复副本"
                )
            result = verify_restore(args.database, args.backup_directory)
    except (ValueError, RuntimeError, sqlite3.Error) as error:
        parser.error(str(error))
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
