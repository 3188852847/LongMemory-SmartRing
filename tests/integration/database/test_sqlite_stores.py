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
    """V1 旧库升级到当前版本后，应保留记忆并回填来源证据。"""

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
    ).fetchone()[0] == 6
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
    """V2 升级到当前版本时，不得丢失已经积累的多条来源。"""

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
    ).fetchone()[0] == 6
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


def test_v3_upgrade_accepts_user_corrected_evidence(tmp_path) -> None:
    """V4 扩展来源枚举时保留 V3 数据，并允许记录人工纠正。"""

    path = tmp_path / "v3.db"
    connection = open_database(path)
    initialize_schema(connection)
    connection.execute("PRAGMA user_version = 3")
    # 模拟 V3 的窄 CHECK：把 V4 表重建为旧约束，再执行真实迁移。
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript("""
        DROP TRIGGER trg_scenario_stale_on_l1_delete;
        DROP TRIGGER trg_scenario_stale_on_l1_retire;
        DROP TABLE scenario_lifecycle_events;
        DROP TABLE scenario_reviews;
        DROP TABLE scenario_generation_audits;
        DROP TABLE scenario_memory_sources;
        DROP TABLE scenario_memories;
        ALTER TABLE memory_evidence RENAME TO memory_evidence_v4_saved;
        CREATE TABLE memory_evidence (
            memory_id TEXT NOT NULL, source_message_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('user_stated')),
            linked_at TEXT NOT NULL,
            PRIMARY KEY (memory_id, source_message_id, source_type),
            FOREIGN KEY (memory_id) REFERENCES atomic_memories(id) ON DELETE CASCADE,
            FOREIGN KEY (source_message_id) REFERENCES conversation_messages(id) ON DELETE RESTRICT
        );
        DROP TABLE memory_evidence_v4_saved;
    """)
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)

    now = datetime(2026, 9, 6, tzinfo=UTC)
    SQLiteConversationStore(connection).save(ConversationMessage(
        MessageId("correction-message"), MessageRole.USER, "用户的猫叫年糕。", now
    ))
    memory = AtomicMemory(MemoryId("corrected-memory"), CURRENT_USER_SUBJECT_ID,
                          "用户的猫叫年糕。", now)
    evidence = MemoryEvidence(memory.id, MessageId("correction-message"),
                              MemorySourceType.USER_CORRECTED, now)
    SQLiteMemoryStore(connection).save(memory, evidence)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert SQLiteMemoryStore(connection).list_evidence(memory.id) == (evidence,)
    connection.close()


def test_v4_upgrade_adds_empty_l2_tables_without_changing_l1(tmp_path) -> None:
    """V4→V5 只增加 L2 结构，不重写既有原话和原子记忆。"""

    path = tmp_path / "v4.db"
    connection = open_database(path)
    initialize_schema(connection)
    connection.executescript("""
        DROP TRIGGER trg_scenario_stale_on_l1_delete;
        DROP TRIGGER trg_scenario_stale_on_l1_retire;
        DROP TABLE scenario_lifecycle_events;
        DROP TABLE scenario_reviews;
        DROP TABLE scenario_generation_audits;
        DROP TABLE scenario_memory_sources;
        DROP TABLE scenario_memories;
        PRAGMA user_version = 4;
    """)
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    SQLiteConversationStore(connection).save(ConversationMessage(
        MessageId("source-v4"), MessageRole.USER, "我周五要答辩。", now
    ))
    memory = AtomicMemory(
        MemoryId("memory-v4"), CURRENT_USER_SUBJECT_ID, "用户周五要答辩。", now
    )
    SQLiteMemoryStore(connection).save(memory, MemoryEvidence(
        memory.id, MessageId("source-v4"), MemorySourceType.USER_STATED, now
    ))

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    assert SQLiteMemoryStore(connection).get(memory.id) == memory
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v5_upgrade_adds_empty_lifecycle_log_and_replaces_triggers(tmp_path) -> None:
    """V5→V6 不伪造历史事件；迁移后新发生的来源退役才产生审计。"""

    path = tmp_path / "v5.db"
    connection = open_database(path)
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC).isoformat()
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id, subject_id, content, recorded_at) VALUES "
        "('l1-v5', 'user:self', '用户周五答辩。', ?)",
        (now,),
    )
    connection.execute(
        "INSERT INTO scenario_memories VALUES "
        "('l2-v5', 'user:self', '准备答辩', '用户周五准备答辩。', ?, NULL, NULL, "
        "'active', 'synthetic', '1', 2)",
        (now,),
    )
    connection.execute(
        "INSERT INTO scenario_memory_sources VALUES "
        "('l2-v5', 'l1-v5', '用户周五答辩。', ?)",
        (now,),
    )
    connection.executescript("""
        DROP TRIGGER trg_scenario_stale_on_l1_retire;
        DROP TRIGGER trg_scenario_stale_on_l1_delete;
        DROP TABLE scenario_lifecycle_events;
        CREATE TRIGGER trg_scenario_stale_on_l1_retire
        AFTER UPDATE OF retired_at ON atomic_memories
        WHEN OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
        BEGIN
            UPDATE scenario_memories SET status='stale', revision=revision+1
            WHERE status IN ('candidate', 'active')
              AND id IN (SELECT scenario_id FROM scenario_memory_sources
                         WHERE memory_id=NEW.id);
        END;
        CREATE TRIGGER trg_scenario_stale_on_l1_delete
        BEFORE DELETE ON atomic_memories
        BEGIN
            UPDATE scenario_memories SET status='stale', revision=revision+1
            WHERE status IN ('candidate', 'active')
              AND id IN (SELECT scenario_id FROM scenario_memory_sources
                         WHERE memory_id=OLD.id);
        END;
        PRAGMA user_version=5;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    assert tuple(connection.execute(
        "SELECT status, revision FROM scenario_memories WHERE id='l2-v5'"
    ).fetchone()) == ("active", 2)
    assert connection.execute(
        "SELECT count(*) FROM scenario_lifecycle_events"
    ).fetchone()[0] == 0
    connection.execute(
        "UPDATE atomic_memories SET retired_at=? WHERE id='l1-v5'", (now,)
    )
    assert tuple(connection.execute(
        "SELECT action, previous_status, scenario_revision "
        "FROM scenario_lifecycle_events WHERE scenario_id='l2-v5'"
    ).fetchone()) == ("source_retired", "active", 3)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_l1_retire_and_delete_make_linked_scenarios_stale(tmp_path) -> None:
    """L1 退出当前集合时，L2 不能继续保持候选或已接受状态。"""

    connection = open_database(tmp_path / "stale.db")
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC).isoformat()
    connection.executemany(
        "INSERT INTO atomic_memories "
        "(id, subject_id, content, recorded_at) VALUES (?, 'user:self', ?, ?)",
        (("l1-a", "用户周五答辩。", now), ("l1-b", "用户正在修改 PPT。", now)),
    )
    connection.execute(
        "INSERT INTO scenario_memories VALUES "
        "('l2-a', 'user:self', '准备答辩', '用户本周正在准备答辩。', ?, NULL, NULL, "
        "'active', 'synthetic', '1', 1)",
        (now,),
    )
    connection.executemany(
        "INSERT INTO scenario_memory_sources VALUES ('l2-a', ?, ?, ?)",
        (("l1-a", "用户周五答辩。", now), ("l1-b", "用户正在修改 PPT。", now)),
    )

    connection.execute("UPDATE atomic_memories SET retired_at=? WHERE id='l1-a'", (now,))
    assert tuple(connection.execute(
        "SELECT status, revision FROM scenario_memories WHERE id='l2-a'"
    ).fetchone()) == ("stale", 2)
    event = connection.execute(
        "SELECT action, actor_type, previous_status, new_status, scenario_revision "
        "FROM scenario_lifecycle_events WHERE scenario_id='l2-a'"
    ).fetchone()
    assert tuple(event) == ("source_retired", "system", "active", "stale", 2)
    # 来源采用带内容快照的弱引用；L1 硬删除后，失效原因仍可审计。
    connection.execute("DELETE FROM atomic_memories WHERE id='l1-b'")
    assert connection.execute(
        "SELECT count(*) FROM scenario_memory_sources WHERE scenario_id='l2-a'"
    ).fetchone()[0] == 2
    # 场景已经失效，删除另一个来源不会重复制造生命周期事件。
    assert connection.execute(
        "SELECT count(*) FROM scenario_lifecycle_events WHERE scenario_id='l2-a'"
    ).fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
