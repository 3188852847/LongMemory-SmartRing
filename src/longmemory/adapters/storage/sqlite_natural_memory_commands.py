"""自然语言记忆操作的 SQLite 原子事务适配器。"""

from pathlib import Path
import sqlite3

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.application.natural_memory_commands import NaturalMemoryCommandService
from longmemory.infrastructure.database.schema import SCHEMA_VERSION


class SQLiteNaturalMemoryCommandHandler:
    """持有独立连接；每条已识别指令要么整体提交，要么整体回滚。"""

    def __init__(self, database: Path) -> None:
        self._connection = sqlite3.connect(
            database.resolve().as_uri() + "?mode=rw", uri=True, timeout=2,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA trusted_schema = OFF")
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            self._connection.close()
            raise ValueError("自然纠正只支持已有的当前版本数据库。")
        self._service = NaturalMemoryCommandService(
            memory_store=SQLiteMemoryStore(self._connection, commit_changes=False),
            conversation_store=SQLiteConversationStore(self._connection, commit_changes=False),
        )

    def handle(self, event):
        if not self._service.recognizes(event):
            return None
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = self._service.handle(event)
            self._connection.commit()
            return result
        except BaseException:
            self._connection.rollback()
            raise

    def close(self) -> None:
        self._connection.close()
