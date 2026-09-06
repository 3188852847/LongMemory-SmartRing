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
from longmemory.infrastructure.database.definition import SCHEMA_VERSION
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
    ).fetchone()[0] == SCHEMA_VERSION
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
    ).fetchone()[0] == SCHEMA_VERSION
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
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
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


def test_v6_upgrade_adds_empty_l3_tables_without_synthesizing_persona(tmp_path) -> None:
    """V6→V7 只增加画像候选结构，不扫描现有 L1/L2 生成结论。"""

    connection = open_database(tmp_path / "v6.db")
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 16, 30, tzinfo=UTC).isoformat()
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id, subject_id, content, recorded_at) VALUES "
        "('l1-v6', 'user:self', '用户喜欢茉莉花茶。', ?)",
        (now,),
    )
    connection.execute(
        "INSERT INTO scenario_memories VALUES "
        "('l2-v6', 'user:self', '近期饮品选择', '用户近期选择茉莉花茶。', "
        "?, NULL, NULL, 'active', 'synthetic', '1', 2)",
        (now,),
    )
    connection.executescript("""
        DROP TRIGGER trg_persona_stale_on_l1_retire;
        DROP TRIGGER trg_persona_stale_on_l1_delete;
        DROP TRIGGER trg_persona_stale_on_l2_stale;
        DROP INDEX idx_persona_lifecycle_persona;
        DROP TABLE persona_lifecycle_events;
        DROP INDEX idx_persona_replacements_target;
        DROP TABLE persona_replacements;
        DROP TABLE persona_reviews;
        DROP TABLE persona_generation_audits;
        DROP INDEX idx_persona_sources_source;
        DROP TABLE persona_sources;
        DROP TABLE persona_memories;
        PRAGMA user_version=6;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM scenario_memories").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM persona_memories").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM persona_sources").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM persona_generation_audits").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM persona_reviews").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v7_upgrade_adds_persona_lifecycle_without_generating_persona(tmp_path) -> None:
    connection = open_database(tmp_path / "v7.db")
    initialize_schema(connection)
    connection.executescript("""
        DROP TRIGGER trg_persona_stale_on_l1_retire;
        DROP TRIGGER trg_persona_stale_on_l1_delete;
        DROP TRIGGER trg_persona_stale_on_l2_stale;
        DROP INDEX idx_persona_lifecycle_persona;
        DROP TABLE persona_lifecycle_events;
        DROP INDEX idx_persona_replacements_target;
        DROP TABLE persona_replacements;
        PRAGMA user_version=7;
    """)
    initialize_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("SELECT count(*) FROM persona_memories").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM persona_lifecycle_events").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v8_upgrade_adds_empty_persona_replacements_without_changing_personas(tmp_path) -> None:
    connection = open_database(tmp_path / "v8.db")
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 18, 0, tzinfo=UTC).isoformat()
    connection.execute(
        "INSERT INTO persona_memories VALUES "
        "('l3-v8','user:self','preference','user_declared','饮品偏好',"
        "'用户喜欢乌龙茶。',?,NULL,NULL,'active','synthetic','1',2)",
        (now,),
    )
    connection.executescript("""
        DROP INDEX idx_persona_replacements_target;
        DROP TABLE persona_replacements;
        PRAGMA user_version=8;
    """)

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert tuple(connection.execute(
        "SELECT statement,status,revision FROM persona_memories WHERE id='l3-v8'"
    ).fetchone()) == ("用户喜欢乌龙茶。", "active", 2)
    assert connection.execute("SELECT count(*) FROM persona_replacements").fetchone()[0] == 0
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


def test_v9_upgrade_preserves_user_review_and_adds_policy_audit_fields(tmp_path) -> None:
    connection = open_database(tmp_path / "v9.db")
    initialize_schema(connection)
    now = datetime(2026, 9, 6, 19, 0, tzinfo=UTC).isoformat()
    connection.execute(
        "INSERT INTO persona_memories VALUES "
        "('l3-v9','user:self','preference','user_declared','饮品偏好',"
        "'用户喜欢乌龙茶。',?,NULL,NULL,'active','synthetic','1',2)",
        (now,),
    )
    # 构造真实 V9 复核表，验证迁移不会把旧人工记录伪装成策略判断。
    connection.executescript("""
        DROP TABLE persona_reviews;
        CREATE TABLE persona_reviews (
            id TEXT PRIMARY KEY,
            persona_id TEXT NOT NULL UNIQUE,
            decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
            reviewer_type TEXT NOT NULL CHECK (reviewer_type = 'user'),
            reviewed_at TEXT NOT NULL,
            persona_revision INTEGER NOT NULL CHECK (persona_revision >= 1),
            FOREIGN KEY (persona_id) REFERENCES persona_memories (id) ON DELETE CASCADE
        );
        PRAGMA user_version=9;
    """)
    connection.execute(
        "INSERT INTO persona_reviews VALUES "
        "('review-v9','l3-v9','accepted','user',?,1)", (now,),
    )
    connection.commit()

    initialize_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    row = connection.execute(
        "SELECT decision,reviewer_type,policy_version,decision_reason "
        "FROM persona_reviews WHERE id='review-v9'"
    ).fetchone()
    assert tuple(row) == ("accepted", "user", None, None)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(persona_reviews)")}
    assert {"policy_version", "decision_reason"} <= columns
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
