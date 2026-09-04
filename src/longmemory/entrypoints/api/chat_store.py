"""网页会话旁库：不改变 L0/L1 schema，不将过去的无会话消息猜测归组。"""
import json
import sqlite3
import os
from pathlib import Path


class ChatStore:
    def __init__(self, database):
        self.path = Path(str(database) + '.chats.sqlite3')
        self.lock = None

    def close(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def load(self):
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
        if not self.path.exists():
            return {}
        try:
            with sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True) as db:
                return {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM web_chats ORDER BY rowid')}
        except Exception:
            self.close()
            raise

    def save(self, key, payload):
        # 仅用户创建/提交/重命名时初始化旁库，启动和读取不会创建个人文件。
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_chats (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('INSERT INTO web_chats VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (key, json.dumps(payload, ensure_ascii=False)))

    def remove(self, key):
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM web_chats WHERE id=?', (key,))
