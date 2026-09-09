"""长期事项跟进合成链：真实 SQLite、模拟圆屏，不访问个人数据。"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from longmemory.adapters.storage.sqlite_proactive_policy_store import (
    SQLiteProactivePolicyStore,
)
from longmemory.core.proactive import OutreachPolicyConfig, ProactivePolicySettings
from longmemory.entrypoints.api.memory_backend import MemoryBackend
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


CREATED = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
DUE = CREATED + timedelta(hours=1)


class ReadyBridge:
    def __init__(self):
        self.announcements = []

    async def status(self):
        return {
            "connection_count": 1, "ready": True,
            "announcement_supported": True, "announcement_ready": True,
            "user_session_active": False,
        }

    async def announce(self, text, expires_at):
        self.announcements.append((text, expires_at))
        return {"state": "queued"}


def prepare(path):
    connection = open_database(path)
    initialize_schema(connection)
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id,subject_id,content,recorded_at,valid_from,valid_to,retired_at,superseded_by_id) "
        "VALUES ('memory-follow-up','user:self',?,?,NULL,NULL,NULL,NULL)",
        ("用户计划今天完善毕业设计汇报。", CREATED.isoformat()),
    )
    SQLiteProactivePolicyStore(connection).save(
        ProactivePolicySettings(
            "user:self",
            OutreachPolicyConfig(
                enabled=True, daily_limit=2, minimum_interval=timedelta(0),
                maximum_lifetime=timedelta(minutes=5),
            ),
            revision=1, updated_at=CREATED,
            automatic_enabled=False,
        ),
        expected_revision=0,
    )
    connection.close()


def create_and_arm(path):
    backend = MemoryBackend(path, clock=lambda: CREATED)
    detail = backend.get("memory-follow-up")
    candidate = backend.create_follow_up_candidate(SimpleNamespace(
        source_memory_id="memory-follow-up",
        expected_memory_revision=detail["revision"],
        prompt_text="毕业设计汇报准备得怎么样了？",
        follow_up_at=DUE,
        request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ))
    return backend.arm_follow_up_candidate(
        candidate["id"], expected_revision=1, expected_policy_revision=1,
    )


def test_armed_follow_up_waits_then_uses_existing_policy_and_delivers_once(tmp_path):
    path = tmp_path / "follow-up-outreach.db"
    prepare(path)
    armed = create_and_arm(path)
    assert armed["activation"]["state"] == "candidate"

    bridge = ReadyBridge()
    early = asyncio.run(
        MemoryBackend(path, clock=lambda: CREATED).proactive_background_tick(bridge)
    )
    assert early["source"] == "routine_absence"
    assert bridge.announcements == []

    first = asyncio.run(
        MemoryBackend(path, clock=lambda: DUE).proactive_background_tick(bridge)
    )
    second = asyncio.run(
        MemoryBackend(path, clock=lambda: DUE).proactive_background_tick(bridge)
    )
    assert first["source"] == "follow_up"
    assert first["result"]["state"] == "queued"
    assert len(bridge.announcements) == 1
    assert second == {
        "source": "follow_up",
        "result": {
            "action": "skip",
            "reason": "follow_up_already_handled_this_minute",
            "suppress_lower_priority": True,
        },
    }
    history = MemoryBackend(path, clock=lambda: DUE).proactive_history()["items"]
    assert history[0]["follow_up_source"] == {
        "candidate_id": armed["id"],
        "candidate_revision": 1,
        "scheduled_for": DUE.isoformat(),
    }


def test_cancelling_armed_follow_up_cancels_future_outreach(tmp_path):
    path = tmp_path / "follow-up-cancel.db"
    prepare(path)
    armed = create_and_arm(path)
    backend = MemoryBackend(path, clock=lambda: CREATED)
    result = backend.cancel_follow_up_candidate(
        armed["id"], expected_revision=1,
    )
    assert result["status"] == "cancelled"
    assert backend.proactive_history()["items"][0]["state"] == "cancelled"


def test_changed_source_is_cancelled_at_due_without_device_delivery(tmp_path):
    path = tmp_path / "follow-up-stale.db"
    prepare(path)
    create_and_arm(path)
    connection = open_database(path)
    connection.execute(
        "UPDATE atomic_memories SET retired_at=? WHERE id='memory-follow-up'",
        ((CREATED + timedelta(minutes=1)).isoformat(),),
    )
    connection.commit()
    connection.close()
    bridge = ReadyBridge()
    result = asyncio.run(
        MemoryBackend(path, clock=lambda: DUE).proactive_follow_up_tick(bridge)
    )
    assert result["state"] == "cancelled"
    assert result["policy_reason"] is None
    assert bridge.announcements == []


def test_deleting_source_cascades_armed_follow_up_and_its_events(tmp_path):
    path = tmp_path / "follow-up-delete.db"
    prepare(path)
    create_and_arm(path)
    connection = open_database(path)
    connection.execute("DELETE FROM atomic_memories WHERE id='memory-follow-up'")
    connection.commit()
    assert connection.execute(
        "SELECT count(*) FROM companion_follow_up_candidates"
    ).fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM proactive_outreach").fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM proactive_outreach_events"
    ).fetchone()[0] == 0
    connection.close()
