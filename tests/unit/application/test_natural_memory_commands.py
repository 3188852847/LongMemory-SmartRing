"""用合成库验证圆屏自然纠正；不访问模型、网络或个人数据。"""

import sqlite3

from longmemory.bootstrap import build_memory_runtime
from longmemory.methods.longmemory_v1.method import LongMemoryV1


def make_runtime(tmp_path):
    database = tmp_path / "natural-commands.db"
    LongMemoryV1(database).close()
    return database, build_memory_runtime(database)


def test_explicit_correction_supersedes_unique_memory_and_keeps_exact_l0(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我养了一只叫豆包的猫")
        result = runtime.prepare_user("不是豆包，是年糕")

        assert result.memory_command.kind == "correct"
        assert result.memory_command.status == "applied"
        assert result.observation.writes[0].operation == "supersede"
        assert "年糕" in result.support.context
        recalled = runtime.prepare_user("我的猫叫什么")
        assert "年糕" in recalled.support.context
        assert "豆包" not in recalled.support.context
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT content FROM conversation_messages WHERE role='user' ORDER BY created_at"
        ).fetchall()
        assert ("不是豆包，是年糕",) in rows
        evidence = connection.execute(
            "SELECT source_type FROM memory_evidence e JOIN atomic_memories m ON m.id=e.memory_id "
            "WHERE m.content LIKE '%年糕%'"
        ).fetchone()
        assert evidence == ("user_corrected",)


def test_explicit_before_now_change_records_valid_time(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我喜欢喝咖啡")
        result = runtime.prepare_user("我以前喜欢喝咖啡，现在不喝咖啡了")
        assert result.memory_command.status == "applied"
        assert result.memory_command.kind == "change"
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        old = connection.execute(
            "SELECT valid_to, retired_at FROM atomic_memories WHERE content='用户喜欢喝咖啡。'"
        ).fetchone()
        new = connection.execute(
            "SELECT valid_from, retired_at FROM atomic_memories WHERE content='用户不喝咖啡了。'"
        ).fetchone()
        assert old[0] is not None and old[1] is not None
        assert new[0] == old[0] and new[1] is None


def test_source_question_returns_original_user_statement_without_new_l1(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我养了一只叫豆包的猫")
        result = runtime.prepare_user("你怎么知道豆包？")
        assert result.memory_command.status == "explained"
        assert "我养了一只叫豆包的猫" in result.memory_command.notice
        assert result.observation.writes == ()
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 1


def test_delete_requires_matching_second_utterance_and_preserves_l0(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我养了一只叫豆包的猫")
        requested = runtime.prepare_user("请忘掉豆包")
        assert requested.memory_command.status == "confirmation_required"
        confirmed = runtime.prepare_user("确认删除这条记忆")
        assert confirmed.memory_command.status == "applied"
        assert confirmed.observation.writes[0].operation == "delete"
        assert "豆包" not in runtime.prepare_user("我的猫叫什么").support.context
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0
        contents = {row[0] for row in connection.execute(
            "SELECT content FROM conversation_messages WHERE role='user'"
        )}
        assert {"我养了一只叫豆包的猫", "请忘掉豆包", "确认删除这条记忆"} <= contents


def test_delete_confirmation_is_cancelled_by_an_unrelated_turn(tmp_path):
    _database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我养了一只叫豆包的猫")
        runtime.prepare_user("请忘掉豆包")
        runtime.prepare_user("我的猫叫什么")
        result = runtime.prepare_user("确认删除这条记忆")
        assert result.memory_command.status == "no_pending_confirmation"
        assert "豆包" in runtime.prepare_user("我的猫叫什么").support.context
    finally:
        runtime.close()


def test_ambiguous_correction_does_not_guess_or_create_correction_fact(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我的猫叫豆包")
        runtime.prepare_user("我的狗叫豆包")
        result = runtime.prepare_user("不是豆包，是年糕")
        assert result.memory_command.status == "ambiguous"
        assert result.observation.writes == ()
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM conversation_messages WHERE content='不是豆包，是年糕'"
        ).fetchone()[0] == 1


def test_unrelated_statement_uses_normal_extraction_path(tmp_path):
    _database, runtime = make_runtime(tmp_path)
    try:
        result = runtime.prepare_user("我喜欢散步")
        assert result.memory_command is None
        assert result.observation.writes[0].operation == "add"
    finally:
        runtime.close()


def test_explicit_exclusion_archives_l0_without_creating_l1(tmp_path):
    database, runtime = make_runtime(tmp_path)
    try:
        result = runtime.prepare_user("不要记住：我今天想喝茉莉花茶")
        assert result.memory_command.kind == "exclude"
        assert result.memory_command.status == "applied"
        assert result.observation.writes == ()
    finally:
        runtime.close()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM atomic_memories").fetchone()[0] == 0
        assert connection.execute(
            "SELECT content FROM conversation_messages WHERE role='user'"
        ).fetchone() == ("不要记住：我今天想喝茉莉花茶",)


def test_ambiguous_exclusion_does_not_retroactively_delete_previous_memory(tmp_path):
    _database, runtime = make_runtime(tmp_path)
    try:
        runtime.prepare_user("我喜欢喝茉莉花茶")
        result = runtime.prepare_user("这句不要记")
        assert result.memory_command.kind == "exclude"
        assert result.memory_command.status == "content_required"
        assert "茉莉花茶" in runtime.prepare_user("我喜欢喝什么").support.context
    finally:
        runtime.close()
