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
from longmemory.core.memory.models import (
    CURRENT_USER_SUBJECT_ID,
    AtomicMemory,
    MemoryEvidence,
    MemorySourceType,
)
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
        subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户养了一只叫豆包的猫。",
        recorded_at=created_at,
    )
    evidence = MemoryEvidence(
        memory_id=memory.id,
        source_message_id=message.id,
        source_type=MemorySourceType.USER_STATED,
        linked_at=created_at,
    )

    # 第一次连接：创建数据库并写入 L0 和 L1。
    first_connection = open_database(database_path)
    initialize_schema(first_connection)

    first_conversation_store = SQLiteConversationStore(first_connection)
    first_memory_store = SQLiteMemoryStore(first_connection)

    first_conversation_store.save(message)
    first_memory_store.save(memory, evidence)

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
    assert reopened_memory_store.list_evidence(memory.id) == (
        evidence,
    )

    assert reopened_memory_store.find_by_content(
        "用户养了一只叫豆包的猫。",
        subject_id=CURRENT_USER_SUBJECT_ID,
    ) == memory

    assert reopened_memory_store.find_by_content(
        "用户养了一只叫不存在的猫。",
        subject_id=CURRENT_USER_SUBJECT_ID,
    ) is None

    reopened_connection.close()


def test_v1_database_is_upgraded_without_losing_source(
    tmp_path,
) -> None:
    """V1 旧库升级到 V3 后，应保留记忆并回填来源证据。"""

    database_path = tmp_path / "v1-longmemory.db"
    created_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)

    # 直接构造旧版结构，避免测试依赖已经升级后的建表代码。
    connection = open_database(database_path)
    connection.executescript(
        """
        CREATE TABLE conversation_messages (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE atomic_memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_message_id)
                REFERENCES conversation_messages (id)
                ON DELETE RESTRICT
        );
        PRAGMA user_version = 1;
        """
    )
    connection.execute(
        """
        INSERT INTO conversation_messages (
            id, role, content, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            "message-v1",
            "user",
            "我养了一只叫豆包的猫。",
            created_at.isoformat(),
        ),
    )
    connection.execute(
        """
        INSERT INTO atomic_memories (
            id, content, source_message_id, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            "memory-v1",
            "用户养了一只叫豆包的猫。",
            "message-v1",
            created_at.isoformat(),
        ),
    )
    connection.commit()

    initialize_schema(connection)

    store = SQLiteMemoryStore(connection)
    evidence = store.list_evidence(MemoryId("memory-v1"))

    assert connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0] == 3
    assert store.get(MemoryId("memory-v1")) == AtomicMemory(
        id=MemoryId("memory-v1"),
        subject_id=CURRENT_USER_SUBJECT_ID,
        content="用户养了一只叫豆包的猫。",
        recorded_at=created_at,
    )
    assert "source_message_id" not in {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(atomic_memories)"
        ).fetchall()
    }
    assert evidence == (
        MemoryEvidence(
            memory_id=MemoryId("memory-v1"),
            source_message_id=MessageId("message-v1"),
            source_type=MemorySourceType.USER_STATED,
            linked_at=created_at,
        ),
    )

    connection.close()


def test_v2_database_preserves_multiple_evidence_during_upgrade(
    tmp_path,
) -> None:
    """V2 升级到 V3 时，不得丢失已经积累的多条来源。"""

    database_path = tmp_path / "v2-longmemory.db"
    connection = open_database(database_path)
    first_time = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    second_time = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)

    connection.executescript(
        """
        CREATE TABLE conversation_messages (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE atomic_memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE memory_evidence (
            memory_id TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            linked_at TEXT NOT NULL,
            PRIMARY KEY (memory_id, source_message_id, source_type)
        );
        PRAGMA user_version = 2;
        """
    )
    connection.executemany(
        """
        INSERT INTO conversation_messages (
            id, role, content, created_at
        ) VALUES (?, 'user', ?, ?)
        """,
        (
            ("message-v2-1", "我养了一只叫豆包的猫。", first_time.isoformat()),
            ("message-v2-2", "我养了一只叫豆包的猫！", second_time.isoformat()),
        ),
    )
    connection.execute(
        """
        INSERT INTO atomic_memories (
            id, content, source_message_id, created_at
        ) VALUES (?, ?, ?, ?)
        """,
        (
            "memory-v2",
            "用户养了一只叫豆包的猫。",
            "message-v2-1",
            first_time.isoformat(),
        ),
    )
    connection.executemany(
        """
        INSERT INTO memory_evidence (
            memory_id, source_message_id, source_type, linked_at
        ) VALUES ('memory-v2', ?, 'user_stated', ?)
        """,
        (
            ("message-v2-1", first_time.isoformat()),
            ("message-v2-2", second_time.isoformat()),
        ),
    )
    connection.commit()

    initialize_schema(connection)

    store = SQLiteMemoryStore(connection)

    assert connection.execute(
        "PRAGMA user_version"
    ).fetchone()[0] == 3
    assert tuple(
        evidence.source_message_id
        for evidence in store.list_evidence(MemoryId("memory-v2"))
    ) == (
        MessageId("message-v2-1"),
        MessageId("message-v2-2"),
    )
    assert connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []

    connection.close()
