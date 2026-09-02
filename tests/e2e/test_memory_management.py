"""验证真实 SQLite 装配下的记忆查看和删除闭环。"""

from longmemory.bootstrap import build_application


def test_memory_can_be_inspected_and_deleted_persistently(
    tmp_path,
) -> None:
    """删除记忆后应立即停止召回，并在重开后保持删除状态。"""

    database_path = tmp_path / "longmemory.db"

    # 第一次启动：通过正常聊天流程生成一条 L1 记忆。
    first_app = build_application(database_path=database_path)
    first_result = first_app.chat(
        "我养了一只叫豆包的猫。"
    )

    saved_memory = first_result.saved_memories[0]
    memory_id = saved_memory.id

    # 管理用例应能列出记忆，并展示其原始 L0 来源。
    listed_memories = first_app.list_memories()

    assert len(listed_memories) == 1
    assert listed_memories[0].memory == saved_memory
    assert tuple(
        source.source_message
        for source in listed_memories[0].sources
    ) == (
        first_result.user_message,
    )

    first_app.close()

    # 第二次启动：确认管理信息也能跨应用实例恢复。
    restarted_app = build_application(
        database_path=database_path
    )

    restored_details = restarted_app.get_memory(memory_id)

    assert restored_details is not None
    assert restored_details.memory.content == (
        "用户养了一只叫豆包的猫。"
    )
    assert len(restored_details.sources) == 1
    assert restored_details.sources[0].source_message is not None
    assert restored_details.sources[0].source_message.content == (
        "我养了一只叫豆包的猫。"
    )

    # 删除 L1 记忆。
    assert restarted_app.delete_memory(memory_id) is True
    assert restarted_app.get_memory(memory_id) is None
    assert restarted_app.list_memories() == ()

    # 删除后，同一应用实例不应再召回该记忆。
    recall_result = restarted_app.chat(
        "我的猫叫什么？"
    )

    assert recall_result.retrieved_memories == ()
    assert recall_result.answer == "我还没有找到相关记忆。"

    restarted_app.close()

    # 第三次启动：确认删除已经持久提交到 SQLite。
    final_app = build_application(database_path=database_path)

    assert final_app.get_memory(memory_id) is None
    assert final_app.list_memories() == ()

    final_app.close()
