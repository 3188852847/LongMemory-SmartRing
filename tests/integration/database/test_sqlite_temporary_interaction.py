from datetime import UTC, datetime, timedelta

from longmemory.adapters.storage.sqlite_temporary_interaction import (
    SQLiteTemporaryInteractionProvider,
)
from longmemory.bootstrap import build_memory_runtime
from longmemory.infrastructure.database.connection import open_database
from longmemory.infrastructure.database.schema import initialize_schema


NOW = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)


def insert_mode(connection, suffix, text, *, recorded_at, valid_to):
    memory_id, message_id = f"l1-{suffix}", f"l0-{suffix}"
    connection.execute(
        "INSERT INTO conversation_messages VALUES (?,?,?,?)",
        (message_id, "user", text, recorded_at.isoformat()),
    )
    connection.execute(
        "INSERT INTO atomic_memories "
        "(id,subject_id,content,recorded_at,valid_from,valid_to) VALUES (?,?,?,?,?,?)",
        (memory_id, "user:self", "用户" + text[1:] + "。", recorded_at.isoformat(),
         recorded_at.isoformat(), valid_to.isoformat()),
    )
    connection.execute(
        "INSERT INTO memory_evidence VALUES (?,?,'user_stated',?)",
        (memory_id, message_id, recorded_at.isoformat()),
    )


def test_provider_uses_latest_effective_explicit_mode_and_stops_at_boundary(tmp_path):
    path = tmp_path / "temporary-interaction.db"
    connection = open_database(path)
    initialize_schema(connection)
    insert_mode(
        connection, "old", "我今天只想让你听我说",
        recorded_at=NOW - timedelta(hours=2), valid_to=NOW + timedelta(hours=8),
    )
    insert_mode(
        connection, "new", "我今天想直接听建议",
        recorded_at=NOW - timedelta(hours=1), valid_to=NOW + timedelta(hours=1),
    )
    connection.commit()
    connection.close()

    provider = SQLiteTemporaryInteractionProvider(path)
    current = provider.current(at=NOW)
    assert current.mode == "direct_advice"
    assert current.source_memory_id == "l1-new"
    assert current.source_message_id == "l0-new"

    # 新设置到期后恢复长期默认，不能让旧临时设置意外“复活”；边界是右开。
    assert provider.current(at=NOW + timedelta(hours=1)) is None


def test_bootstrapped_runtime_keeps_today_mode_across_following_turns(tmp_path):
    path = tmp_path / "runtime-temporary-interaction.db"
    connection = open_database(path)
    initialize_schema(connection)
    connection.close()
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    try:
        selected = runtime.prepare_user("我今天只想让你听我说")
        assert selected.temporary_interaction.mode == "listen_only"

        following = runtime.prepare_user("项目压力有点大")
        assert following.temporary_interaction.mode == "listen_only"
        assert "不主动分析" in following.support.context
        assert any(
            item.item_id == selected.temporary_interaction.source_memory_id
            for item in following.support.retrieved
        )

        restored = runtime.prepare_user("我今天恢复默认互动方式")
        assert restored.temporary_interaction is None
        assert runtime.prepare_user("继续聊项目").temporary_interaction is None
    finally:
        runtime.close()


def test_latest_explicit_default_stops_mode_without_resurrecting_old_choice(tmp_path):
    path = tmp_path / "temporary-default.db"
    connection = open_database(path)
    initialize_schema(connection)
    insert_mode(
        connection, "listen", "我今天只想让你听我说",
        recorded_at=NOW - timedelta(hours=1), valid_to=NOW + timedelta(hours=8),
    )
    insert_mode(
        connection, "default", "我今天恢复默认互动方式",
        recorded_at=NOW, valid_to=NOW + timedelta(hours=8),
    )
    connection.commit()
    connection.close()

    assert SQLiteTemporaryInteractionProvider(path).current(at=NOW) is None


def test_bootstrapped_next_turn_mode_archives_l0_without_creating_l1(tmp_path):
    path = tmp_path / "next-turn-interaction.db"
    connection = open_database(path)
    initialize_schema(connection)
    connection.close()
    runtime = build_memory_runtime(path, clock=lambda: NOW)
    try:
        armed = runtime.prepare_user("下一轮只听我说")
        assert armed.memory_command.kind == "set_next_interaction"
        assert armed.observation.writes == ()

        used = runtime.prepare_user("我今天在项目上碰到了一些困难")
        assert used.temporary_interaction.mode == "listen_only"
        assert used.temporary_interaction.scope == "next_turn"
        assert runtime.prepare_user("再说一件事").temporary_interaction is None

        connection = open_database(path)
        try:
            assert connection.execute(
                "SELECT count(*) FROM conversation_messages WHERE id=?",
                (armed.event.event_id,),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT count(*) FROM atomic_memories "
                "WHERE content LIKE '%下一轮只听我说%'",
            ).fetchone()[0] == 0
        finally:
            connection.close()
    finally:
        runtime.close()
