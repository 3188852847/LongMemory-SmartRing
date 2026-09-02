"""验证最小长程记忆能够跨应用生命周期保存并回忆。"""

from longmemory.adapters.storage.sqlite_conversation_store import (
    SQLiteConversationStore,
)
from longmemory.bootstrap import build_application
from longmemory.core.conversation.models import MessageRole
from longmemory.infrastructure.database.connection import open_database


def test_memory_survives_application_restart(tmp_path) -> None:
    """关闭并重新创建应用后，仍然能够从 SQLite 中找回记忆。"""

    # pytest 会为当前测试创建一个临时目录。
    # 这样不会污染真实数据，也不会让不同测试互相影响。
    database_path = tmp_path / "longmemory.db"

    # 第一次启动应用，告诉它一条值得长期保存的信息。
    first_app = build_application(database_path=database_path)
    first_result = first_app.chat("我养了一只叫豆包的猫。")

    # 这句话应该被提取并规范化为一条长期记忆。
    assert len(first_result.saved_memories) == 1

    saved_memory = first_result.saved_memories[0]
    assert saved_memory.content == "用户养了一只叫豆包的猫。"

    # 记忆必须保留来源，方便以后检查它是从哪条原始输入提取出来的。
    assert first_result.memory_operations[0].evidence.source_message_id == (
        first_result.user_message.id
    )

    # 关闭第一个应用实例，模拟程序退出。
    first_app.close()

    # 直接重新打开数据库，确认助手回答也作为 L0 原文持久化。
    inspection_connection = open_database(database_path)
    conversation_store = SQLiteConversationStore(
        inspection_connection
    )
    restored_assistant = conversation_store.get(
        first_result.assistant_message.id
    )

    assert restored_assistant == first_result.assistant_message
    assert restored_assistant.role == MessageRole.ASSISTANT

    inspection_connection.close()

    # 使用同一个 SQLite 文件重新创建应用。
    # 如果记忆只是存在内存中，这一步之后就会丢失。
    restarted_app = build_application(database_path=database_path)
    recall_result = restarted_app.chat("我的猫叫什么？")

    # 查询问题本身不应该被错误地保存为长期记忆。
    assert recall_result.saved_memories == ()

    # 应该能检索到上一次运行中保存的记忆。
    assert [
        memory.content for memory in recall_result.retrieved_memories
    ] == [
        "用户养了一只叫豆包的猫。"
    ]

    # 最终回答应该使用检索到的记忆。
    assert recall_result.answer == "你的猫叫豆包。"

    restarted_app.close()
