"""网页会话旁库：不改变 L0/L1 schema，不将过去的无会话消息猜测归组。"""
from contextlib import closing
import json
import sqlite3
import os
from pathlib import Path


class ChatStore:
    def __init__(self, database):
        self.path = Path(str(database) + '.chats.sqlite3').absolute()
        self.lock = None

    def close(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def open(self):
        # 整个控制台生命周期独占旁库，拒绝两个端口同时覆盖会话快照。
        self.lock = self.path.with_suffix(self.path.suffix + '.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.close()
            raise ValueError('此记忆库已有控制台管理会话，请先停止旧控制台。') from None

    def _read(self):
        return closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True))

    def get(self, key):
        if not self.path.exists():
            return None
        with self._read() as db:
            row = db.execute('SELECT payload FROM web_chats WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def summaries(self, owner, active):
        if not owner or not self.path.exists():
            return []
        with self._read() as db:
            rows = db.execute("""SELECT id, json_extract(payload, '$.title'),
                json_array_length(payload, '$.turns'), json_extract(payload, '$.pending'),
                json_type(payload, '$.active_request') FROM web_chats
                WHERE json_extract(payload, '$.owner')=? ORDER BY rowid DESC""", (owner,))
            # 上次中断的请求在打开会话时恢复为一轮；正在运行的请求还没有结果。
            return [dict(chat_id=key, title=title, turn_count=count + int(
                bool(pending) and active_type == "object" and key not in active))
                for key, title, count, pending, active_type in rows]

    def owned(self, owner):
        # 仅在显式查询历史反馈时遍历正文；日常聊天按编号只读一份。
        if owner and self.path.exists():
            with self._read() as db:
                for key, payload in db.execute(
                    "SELECT id, payload FROM web_chats WHERE json_extract(payload, '$.owner')=?", (owner,)
                ):
                    yield key, json.loads(payload)

    def create(self, key, payload):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS web_chats (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT INTO web_chats VALUES (?, ?)', (key, json.dumps(payload, ensure_ascii=False)))

    def save(self, key, payload):
        with closing(sqlite3.connect(self.path)) as db, db:
            result = db.execute('UPDATE web_chats SET payload=? WHERE id=?',
                                (json.dumps(payload, ensure_ascii=False), key))
            if result.rowcount != 1:
                raise KeyError(key)

    def remove(self, key):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM web_chats WHERE id=?', (key,))
