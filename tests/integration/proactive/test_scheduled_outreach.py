"""定时问候合成链：真实 SQLite、模拟圆屏桥，不访问个人数据或设备。"""

import asyncio
import sqlite3
from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 7, 5, 0, 10, tzinfo=UTC)  # 北京时间周一 13:00。


class ReadyBridge:
    def __init__(self):
        self.announcements = []

    async def status(self):
        return {
            "connection_count": 1,
            "ready": True,
            "read_volume_supported": True,
            "set_volume_supported": True,
            "announcement_supported": True,
            "announcement_ready": True,
            "user_session_active": False,
            "allowed_volume": {"minimum": 5, "maximum": 60},
        }

    async def announce(self, text, expires_at):
        self.announcements.append((text, expires_at))
        return {"state": "queued"}


def prepare(path, *, user_chatted=False):
    connection = open_database(path)
    initialize_schema(connection)
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(enabled=True),
            revision=1,
            updated_at=NOW,
            automatic_enabled=True,
            scheduled_minute=13 * 60,
            greeting_text="固定合成问候。",
        ),
        expected_revision=0,
    )
    if user_chatted:
        connection.execute(
            "INSERT INTO conversation_messages(id,role,content,created_at) "
            "VALUES ('synthetic-user-message','user','合成文本',?)",
            (NOW.replace(hour=1).isoformat(),),
        )
        connection.commit()
    connection.close()


def test_exact_minute_dispatches_at_most_once_across_repeated_ticks(tmp_path):
    path = tmp_path / "scheduled.db"
    prepare(path)
    bridge = ReadyBridge()
    backend = MemoryBackend(path, clock=lambda: NOW)

    first = asyncio.run(backend.proactive_scheduled_tick(bridge))
    second = asyncio.run(backend.proactive_scheduled_tick(bridge))

    assert first["state"] == "queued"
    assert second == {"action": "skip", "reason": "already_evaluated_today"}
    assert [item[0] for item in bridge.announcements] == ["固定合成问候。"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_kind,state FROM proactive_outreach"
        ).fetchone() == ("explicit_schedule", "queued")


def test_real_user_chat_that_day_skips_without_creating_outreach(tmp_path):
    path = tmp_path / "already-chatted.db"
    prepare(path, user_chatted=True)
    bridge = ReadyBridge()

    result = asyncio.run(
        MemoryBackend(path, clock=lambda: NOW).proactive_scheduled_tick(bridge)
    )

    assert result == {"action": "skip", "reason": "user_already_chatted_today"}
    assert bridge.announcements == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0
