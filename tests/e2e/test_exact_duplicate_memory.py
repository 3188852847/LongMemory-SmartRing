"""验证完全相同的规范化记忆不会重复写入。"""

from longmemory.bootstrap import build_application


def test_exact_duplicate_memory_is_reused_after_restart(
    tmp_path,
) -> None:
    """标点不同但规范化内容相同的输入应复用同一条 L1。"""

    database_path = tmp_path / "longmemory.db"

    first_app = build_application(
        database_path=database_path
    )

    try:
        first_result = first_app.chat(
            "我养了一只叫豆包的猫。"
        )
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
        assert tuple(
            source.source_message.content
            for source in listed_memories[0].sources
            if source.source_message is not None
        ) == (
            "我养了一只叫豆包的猫。",
            "我养了一只叫豆包的猫！",
        )
    finally:
        first_app.close()

    # 数据库重开后，仍然应识别已有的规范化内容。
    restarted_app = build_application(
        database_path=database_path
    )

    try:
        restarted_duplicate = restarted_app.chat(
            "我养了一只叫豆包的猫"
        )

        assert restarted_duplicate.saved_memories == ()
        assert restarted_duplicate.reused_memories == (
            original_memory,
        )

        restarted_details = restarted_app.list_memories()
        assert len(restarted_details) == 1
        assert len(restarted_details[0].sources) == 3
    finally:
        restarted_app.close()
