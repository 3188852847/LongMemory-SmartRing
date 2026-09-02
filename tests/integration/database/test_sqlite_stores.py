"""验证 L0 和 L1 数据能够通过 SQLite 跨连接持久化。"""

from datetime import UTC, datetime

from longmemory.adapters.storage.sqlite_conversation_store import (
    SQLiteConversationStore,
)
from longmemory.adapters.storage.sqlite_memory_store import SQLiteMemoryStore
from longmemory.core.common.identifiers import MemoryId, MessageId
from longmemory.core.conversation.models import (
    ConversationMessage,
    MessageRole,
)
from longmemory.core.memory.models import AtomicMemory
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


def test_message_and_memory_survive_database_reopen(tmp_path) -> None:
    """关闭并重新打开数据库后，消息和记忆仍然存在。"""

    database_path = tmp_path / "longmemory.db"
    created_at = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

    message = ConversationMessage(
        id=MessageId("message-001"),
        role=MessageRole.USER,
        content="我养了一只叫豆包的猫。",
        created_at=created_at,
    )

    memory = AtomicMemory(
        id=MemoryId("memory-001"),
        content="用户养了一只叫豆包的猫。",
        source_message_id=message.id,
        created_at=created_at,
    )

    # 第一次连接：创建数据库并写入 L0 和 L1。
    first_connection = open_database(database_path)
    initialize_schema(first_connection)

    first_conversation_store = SQLiteConversationStore(first_connection)
    first_memory_store = SQLiteMemoryStore(first_connection)

    first_conversation_store.save(message)
    first_memory_store.save(memory)

    first_connection.close()

    # 第二次连接：模拟程序重新启动后重新打开数据库。
    reopened_connection = open_database(database_path)
    initialize_schema(reopened_connection)

    reopened_conversation_store = SQLiteConversationStore(reopened_connection)
    reopened_memory_store = SQLiteMemoryStore(reopened_connection)

    restored_message = reopened_conversation_store.get(message.id)
    restored_memory = reopened_memory_store.get(memory.id)

    assert restored_message == message
    assert restored_memory == memory
    assert reopened_memory_store.list_all() == (memory,)

    reopened_connection.close()