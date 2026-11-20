"""验证完全相同的规范化记忆不会重复写入。"""

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest

from longmemory.application.memory_management.dto import MemoryEvidenceDetails
from longmemory.bootstrap import build_application
from longmemory.core.common.identifiers import MessageId
from longmemory.methods.longmemory_v1 import method as legacy_method


@pytest.mark.parametrize(
    "delay", [timedelta(seconds=1), timedelta(0)], ids=["distinct-time", "same-time"],
)
def test_exact_duplicate_memory_is_reused_after_restart(
    tmp_path, monkeypatch, delay,
) -> None:
    """标点不同但规范化内容相同的输入应复用同一条 L1。"""

    database_path = tmp_path / "longmemory.db"
    now = datetime(2026, 11, 21, 8, tzinfo=UTC)
    # 固定 ID 与写入次序相反，使同一时刻的两条来源可重复验证。
    ids = iter((MessageId("user-03"), MessageId("user-02"), MessageId("user-01")))
    monkeypatch.setattr(legacy_method, "MemoryTurnService", partial(
        legacy_method.MemoryTurnService, message_id_factory=ids.__next__, clock=lambda: now,
    ))
    monkeypatch.setattr(legacy_method, "MemoryExtractionService", partial(
        legacy_method.MemoryExtractionService, clock=lambda: now,
    ))

    first_app = build_application(
        database_path=database_path
    )

    try:
        first_result = first_app.chat(
            "我养了一只叫豆包的猫。"
        )
        now += delay
        duplicate_result = first_app.chat(
            "我养了一只叫豆包的猫！"
        )

        assert len(first_result.saved_memories) == 1
        original_memory = first_result.saved_memories[0]

        assert duplicate_result.saved_memories == ()
        assert duplicate_result.reused_memories == (
            original_memory,
        )

        listed_memories = first_app.list_memories()
        assert len(listed_memories) == 1
        first = MemoryEvidenceDetails(
            first_result.memory_operations[0].evidence, first_result.user_message,
        )
        second = MemoryEvidenceDetails(
            duplicate_result.memory_operations[0].evidence, duplicate_result.user_message,
        )
        assert first.source_message.content == "我养了一只叫豆包的猫。"
        assert second.source_message.content == "我养了一只叫豆包的猫！"
        assert first.evidence.linked_at == now - delay and second.evidence.linked_at == now
        # 读取契约以关联时间为第一顺位，同一时间再比较消息 ID。
        expected_sources = (second, first) if delay == timedelta(0) else (first, second)
        assert listed_memories[0].sources == expected_sources
    finally:
        first_app.close()

    # 数据库重开后，仍然应识别已有的规范化内容。
    restarted_app = build_application(
        database_path=database_path
    )

    try:
        assert restarted_app.list_memories() == listed_memories
        now += timedelta(seconds=1)
        restarted_duplicate = restarted_app.chat(
            "我养了一只叫豆包的猫"
        )

        assert restarted_duplicate.saved_memories == ()
        assert restarted_duplicate.reused_memories == (
            original_memory,
        )

        restarted_details = restarted_app.list_memories()
        assert len(restarted_details) == 1
        third = MemoryEvidenceDetails(
            restarted_duplicate.memory_operations[0].evidence, restarted_duplicate.user_message,
        )
        assert third.source_message.content == "我养了一只叫豆包的猫"
        assert third.evidence.linked_at == now
        assert restarted_details[0].sources == (*expected_sources, third)
    finally:
        restarted_app.close()
