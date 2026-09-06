"""管理网页对已有库的非迁移访问；所有写入和删除均限 pytest 合成库。"""

import hashlib
import sqlite3

import pytest

from longmemory.bootstrap import build_application
from longmemory.entrypoints.api.memory_backend import MemoryBackend, MemoryAccessError


@pytest.fixture
def recorded(tmp_path):
    path = tmp_path / "合成测试 空格.db"
    app = build_application(database_path=path)
    result = app.chat("我养了一只叫豆包的猫。")
    app.close()
    return path, str(result.saved_memories[0].id), str(result.user_message.id)


def test_read_only_browse_does_not_change_file(recorded):
    path, memory_id, _ = recorded
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    backend = MemoryBackend(path)
    assert backend.list_page()["total"] == 1
    details = backend.get(memory_id)
    assert details["subject_id"] == "user:self"
    assert details["valid_from"] is None  # 不拿系统记录时间冒充事实生效时间。
    assert details["sources"][0]["source_type"] == "user_stated"
    with pytest.raises(MemoryAccessError, match="memory_read_only"):
        backend.delete(memory_id, details["revision"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "not-created" / "missing.db"
    with pytest.raises(MemoryAccessError, match="memory_database_missing"):
        MemoryBackend(path).list_page()
    assert not path.parent.exists()


@pytest.mark.parametrize("version", [0, 1, 2, 3, 5])
def test_old_and_unknown_schema_are_not_migrated(tmp_path, version):
    path = tmp_path / "version.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"PRAGMA user_version={version}")
    before = path.read_bytes()
    with pytest.raises(MemoryAccessError, match="memory_schema_unsupported"):
        MemoryBackend(path).list_page()
    assert path.read_bytes() == before


def test_source_changes_invalidate_delete_confirmation(recorded):
    path, memory_id, _ = recorded
    backend = MemoryBackend(path, allow_delete=True)
    before = backend.get(memory_id)
    app = build_application(database_path=path)
    app.chat("我养了一只叫豆包的猫。")
    app.close()
    with pytest.raises(MemoryAccessError, match="memory_changed"):
        backend.delete(memory_id, before["revision"])
    after = backend.get(memory_id)
    assert len(after["sources"]) == 2
    assert after["revision"] != before["revision"]


def test_pagination_filter_and_literal_search(recorded):
    path, memory_id, _ = recorded
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT * FROM atomic_memories WHERE id=?", (memory_id,)).fetchone()
        for index in range(5):
            values = list(row)
            values[0], values[2] = f"synthetic-{index}", f"用户喜欢 coffee {index}。"
            if index == 4: values[6] = "2026-09-03T00:00:00+00:00"
            conn.execute("INSERT INTO atomic_memories VALUES (?,?,?,?,?,?,?,?)", values)
    backend = MemoryBackend(path)
    first = backend.list_page(limit=2)
    second = backend.list_page(limit=2, offset=2)
    assert first["total"] == 5
    assert len(first["items"]) == len(second["items"]) == 2
    assert {m["id"] for m in first["items"]}.isdisjoint(m["id"] for m in second["items"])
    assert backend.list_page(query="COFFEE")["total"] == 4
    assert backend.list_page(state="all")["total"] == 6
    assert backend.list_page(state="retired")["total"] == 1
    assert backend.list_page(query="%' OR 1=1 --")["total"] == 0


def test_delete_preserves_l0_and_clears_incoming_supersede_link(recorded):
    path, memory_id, source_id = recorded
    with sqlite3.connect(path) as conn:
        row = list(conn.execute("SELECT * FROM atomic_memories WHERE id=?", (memory_id,)).fetchone())
        row[0], row[6], row[7] = "synthetic-old", "2026-09-03T00:00:00+00:00", memory_id
        conn.execute("INSERT INTO atomic_memories VALUES (?,?,?,?,?,?,?,?)", row)
    backend = MemoryBackend(path, allow_delete=True)
    detail = backend.get(memory_id)
    assert backend.delete(memory_id, detail["revision"])["deleted"] is True
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_evidence WHERE memory_id=?", (memory_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM conversation_messages WHERE id=?", (source_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT superseded_by_id FROM atomic_memories WHERE id='synthetic-old'").fetchone()[0] is None


def test_markup_is_returned_as_data_not_rewritten_as_fact(recorded):
    path, memory_id, source_id = recorded
    attack = '<img src=x onerror="alert(1)"><script>synthetic</script>'
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE atomic_memories SET content=? WHERE id=?", (attack, memory_id))
        conn.execute("UPDATE conversation_messages SET content=? WHERE id=?", (attack, source_id))
    detail = MemoryBackend(path).get(memory_id)
    assert detail["content"] == attack
    assert detail["sources"][0]["message"]["content"] == attack


def test_missing_source_is_visible_in_details(recorded):
    path, memory_id, source_id = recorded
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM conversation_messages WHERE id=?", (source_id,))
    assert MemoryBackend(path).get(memory_id)["sources"][0]["message"] is None


def test_correction_requires_capability_and_preserves_auditable_history(recorded):
    path, memory_id, source_id = recorded
    detail = MemoryBackend(path).get(memory_id)
    with pytest.raises(MemoryAccessError, match="memory_correction_disabled"):
        MemoryBackend(path).correct(memory_id, "用户的猫叫年糕。", detail["revision"])

    backend = MemoryBackend(path, allow_correction=True)
    result = backend.correct(memory_id, "用户的猫叫年糕。", detail["revision"])
    assert result["corrected"] is True
    old = backend.get(memory_id)
    new = backend.get(result["new_memory_id"])
    assert old["state"] == "retired" and old["superseded_by_id"] == new["id"]
    assert new["state"] == "active" and new["content"] == "用户的猫叫年糕。"
    assert new["sources"][0]["source_type"] == "user_corrected"
    assert new["sources"][0]["message"]["content"] == "用户的猫叫年糕。"
    assert backend.list_page()["items"][0]["id"] == new["id"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages WHERE id=?", (source_id,)).fetchone()[0] == 1


def test_correction_rejects_stale_revision_without_partial_write(recorded):
    path, memory_id, _ = recorded
    backend = MemoryBackend(path, allow_correction=True)
    before = backend.get(memory_id)
    with pytest.raises(MemoryAccessError, match="memory_changed"):
        backend.correct(memory_id, "用户的猫叫年糕。", "0" * 64)
    assert backend.get(memory_id) == before
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM atomic_memories").fetchone()[0] == 1
