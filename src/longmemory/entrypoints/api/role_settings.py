"""助手角色设置旁库：与个人记忆分离，只在用户明确保存时创建。

版本用于并发检查和回答追溯，不代表 L3 用户画像，也不向小智同步。
"""
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

PRESETS = ('plain_v1', 'elysia_v1')


def preset_prompt(name):
    if name not in PRESETS:
        raise ValueError('invalid_preset')
    source = Path(__file__).resolve().parents[2] / 'prompts/personas' / (name + '.txt')
    return source.read_text(encoding='utf-8').replace('<memory></memory>', '（证据见独立 memory_evidence 消息。）')


class RoleConflict(ValueError):
    pass


class RoleSettings:
    def __init__(self, database, default_role):
        self.path = Path(str(database) + '.role.sqlite3')
        self.default_role = default_role

    def default(self):
        return {'revision': 0, 'name': self.default_role, 'prompt': preset_prompt(self.default_role), 'saved_at': None}

    @staticmethod
    def latest(connection):
        row = connection.execute('SELECT revision,name,prompt,saved_at FROM assistant_roles ORDER BY revision DESC LIMIT 1').fetchone()
        return dict(zip(('revision', 'name', 'prompt', 'saved_at'), row)) if row else None

    def current(self):
        if not self.path.exists():
            return self.default()
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)) as connection:
            return self.latest(connection) or self.default()

    def save(self, *, expected_revision, name, prompt):
        if (type(expected_revision) is not int or expected_revision < 0 or
                not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or
                not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 12000 or '\x00' in prompt):
            raise ValueError('invalid_role')
        # BEGIN IMMEDIATE 让不同浏览器/进程不能同时用旧版本覆盖新版本。
        with closing(sqlite3.connect(self.path, timeout=2)) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('CREATE TABLE IF NOT EXISTS assistant_roles (revision INTEGER PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, saved_at TEXT NOT NULL)')
                previous = self.latest(connection)
                revision = previous['revision'] if previous else 0
                if revision != expected_revision:
                    raise RoleConflict('role_conflict')
                connection.execute('INSERT INTO assistant_roles VALUES (?,?,?,?)',
                                   (revision + 1, name.strip(), prompt.strip(), datetime.now(UTC).isoformat()))
                return self.latest(connection)
