"""新后端的平台来源账本，复用现有原文存储，不初始化旧派生表。

仅显式 create=True 创建新文件，不迁移/打开个人 L0–L3 库。
同一来源库同时只有一个拥有者，进程退出后 OS 自动释放文件锁。
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from longmemory.adapters.storage.sqlite_conversation_store import SQLiteConversationStore
from longmemory.core.common.identifiers import MessageId
from longmemory.core.conversation.models import ConversationMessage, MessageRole
from longmemory.methods.contracts import MemoryEvent, ObservationResult, WriteTrace


class SQLiteSourceJournal:
    def __init__(self, path: Path, *, engine_name: str, create: bool = False):
        self.path = path.resolve()
        self._lease = None
        self.closed = False
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 排他创建；传错已有文件不能把个人库加表或清空。
            with self.path.open("xb"):
                pass
        elif not self.path.is_file():
            raise FileNotFoundError("source_journal_missing")
        try:
            self._lease = self.path.with_suffix(self.path.suffix + ".owner").open("a+b")
            self._lease.seek(0)
            if os.name == "nt":
                import msvcrt
                if self._lease.read(1) == b"":
                    self._lease.write(b"0")
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self._connect() as connection:
                if create:
                    connection.executescript("""
                        CREATE TABLE conversation_messages (
                            id TEXT PRIMARY KEY, role TEXT NOT NULL,
                            content TEXT NOT NULL, created_at TEXT NOT NULL);
                        CREATE TABLE source_journal_identity (engine_name TEXT NOT NULL);
                        CREATE TABLE source_dispatch (
                            event_id TEXT PRIMARY KEY REFERENCES conversation_messages(id),
                            session_id TEXT, state TEXT NOT NULL,
                            attempt_id TEXT, result TEXT);
                    """)
                    connection.execute("INSERT INTO source_journal_identity VALUES (?)", (engine_name,))
                row = connection.execute("SELECT engine_name FROM source_journal_identity").fetchone()
                if row is None or row[0] != engine_name:
                    raise ValueError("source_journal_engine_mismatch")
                # 拥有独占生命周期锁后，前任 running 才能判为不确定。
                connection.execute("UPDATE source_dispatch SET state='uncertain' WHERE state='running'")
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _connect(self):
        if self.closed:
            raise RuntimeError("source_journal_closed")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _event(connection, event_id):
        message = SQLiteConversationStore(connection).get(MessageId(event_id))
        if message is None:
            raise LookupError("source_not_found")
        row = connection.execute("SELECT session_id FROM source_dispatch WHERE event_id=?", (event_id,)).fetchone()
        return MemoryEvent(event_id, message.role.value, message.content, message.created_at, row[0])

    def archive(self, event: MemoryEvent):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute("SELECT 1 FROM source_dispatch WHERE event_id=?", (event.event_id,)).fetchone()
            if exists:
                if self._event(connection, event.event_id) != event:
                    raise ValueError("source_event_conflict")
                return
            SQLiteConversationStore(connection, commit_changes=False).save(ConversationMessage(
                MessageId(event.event_id), MessageRole(event.role), event.content, event.occurred_at,
            ))
            connection.execute("INSERT INTO source_dispatch VALUES (?,?,'archived',NULL,NULL)", (event.event_id, event.session_id))

    def get(self, event_id):
        with self._connect() as connection:
            event = self._event(connection, event_id)
            row = connection.execute("SELECT state,attempt_id,result FROM source_dispatch WHERE event_id=?", (event_id,)).fetchone()
            return event, dict(row)

    def events(self):
        with self._connect() as connection:
            ids = connection.execute("SELECT event_id FROM source_dispatch ORDER BY rowid").fetchall()
            return tuple(self._event(connection, row[0]) for row in ids)

    def begin(self, event_id, *, expected_attempt_id=None, retry=False):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM source_dispatch WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise LookupError("source_not_found")
            if retry:
                if row["state"] not in {"failed", "uncertain", "pending"} or row["attempt_id"] != expected_attempt_id:
                    raise ValueError("source_retry_changed")
            elif row["state"] not in {"archived", "pending"}:
                raise ValueError("source_dispatch_not_ready")
            attempt = str(uuid4())
            connection.execute("UPDATE source_dispatch SET state='running',attempt_id=?,result=NULL WHERE event_id=?", (attempt, event_id))
            return attempt

    def defer(self, event_id):
        with self._connect() as connection:
            connection.execute("UPDATE source_dispatch SET state='pending',attempt_id=? WHERE event_id=? AND state='archived'",
                               (str(uuid4()), event_id))

    def finish(self, event_id, attempt_id, result: ObservationResult):
        data = json.dumps(asdict(result), ensure_ascii=False)
        with self._connect() as connection:
            updated = connection.execute("UPDATE source_dispatch SET state=?,result=? WHERE event_id=? AND attempt_id=? AND state='running'", (
                "completed" if result.processing_status == "completed" else "failed", data, event_id, attempt_id,
            )).rowcount
            if updated != 1:
                raise ValueError("source_attempt_changed")

    @staticmethod
    def result(data):
        value = json.loads(data)
        writes = value["writes"]
        value["writes"] = None if writes is None else tuple(WriteTrace(
            item["operation"], item["item_id"], tuple(item["source_event_ids"]),
        ) for item in writes)
        return ObservationResult(**value)

    def close(self):
        if self._lease is not None:
            self._lease.close()
            self._lease = None
        self.closed = True
