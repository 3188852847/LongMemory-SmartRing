"""用合成数据库核对方法边界，不调用学校模型、不触碰日常记忆。"""

import ast
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

import pytest

from longmemory.bootstrap import build_application, open_memory_service
from longmemory.methods import contracts
from longmemory.methods.contracts import (
    MemoryEvent, UnsupportedCapabilityError, require_capability,
)
from longmemory.methods.factory import create_method


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def event(event_id="user-1", content="我养了一只叫豆包的猫", role="user", session_id=None):
    return MemoryEvent(event_id, role, content, NOW, session_id)


def rows(path):
    # 直接检查 L0：确保 recall 没有把测试问题当作新的历史保存。
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT id, role, content, created_at FROM conversation_messages ORDER BY id"
        ).fetchall()


def test_observe_recall_preserves_source_and_reopen(tmp_path):
    path = tmp_path / "synthetic.db"
    method = create_method(name="longmemory_v1", state_path=path)
    try:
        written = method.observe(event())
        method.wait_until_ready()
        assert written.writes[0].operation == "add"
        assert written.writes[0].source_event_ids == ("user-1",)
        method.observe(event("assistant-1", "我养了一只叫花花的猫", "assistant"))
        assert rows(path) == [
            ("assistant-1", "assistant", "我养了一只叫花花的猫", NOW.isoformat()),
            ("user-1", "user", "我养了一只叫豆包的猫", NOW.isoformat()),
        ]
        before = path.read_bytes()
        support = method.recall("我的猫叫什么")
        assert "豆包" in support.context and "花花" not in support.context
        assert support.retrieved[0].source_event_ids == ("user-1",)
        assert support.retrieval_strategy == "keyword_v1"
        assert support.retrieved[0].keyword_score == 1
        assert support.retrieved[0].dense_score is None
        assert support.retrieved[0].fused_score is None
        assert path.read_bytes() == before
        assert method.recall("我的猫叫什么").call_id != support.call_id
        duplicate = method.observe(event("user-2"))
        assert duplicate.writes[0].operation == "noop"
        assert method.recall("我的猫叫什么").retrieved[0].source_event_ids == ("user-1", "user-2")
    finally:
        method.close()
    method.close()
    assert path.exists()
    reopened = create_method(name="longmemory_v1", state_path=path)
    try:
        assert "豆包" in reopened.recall("我的猫叫什么").context
    finally:
        reopened.close()


def test_empty_result_is_not_missing_trace_and_state_is_isolated(tmp_path):
    first = create_method(name="longmemory_v1", state_path=tmp_path / "first.db")
    second = create_method(name="longmemory_v1", state_path=tmp_path / "second.db")
    try:
        first.observe(event())
        result = second.recall("我的猫叫什么")
        assert result.retrieved == ()
        assert "豆包" not in result.context
        assert rows(tmp_path / "second.db") == []
    finally:
        first.close()
        second.close()


def test_unsupported_operations_fail_before_writes(tmp_path):
    path = tmp_path / "state.db"
    method = create_method(name="longmemory_v1", state_path=path)
    try:
        for capability in ("session_metadata", "feedback_learning", "frozen_evaluation"):
            with pytest.raises(UnsupportedCapabilityError):
                require_capability(method, capability)
        require_capability(method, "source_trace")
        with pytest.raises(ValueError):
            require_capability(method, "misspelled_capability")
        with pytest.raises(UnsupportedCapabilityError):
            method.observe(event(session_id="session-1"))
        assert rows(path) == []
    finally:
        method.close()


@pytest.mark.parametrize("operation", ["observe", "recall", "wait_until_ready"])
def test_closed_method_cannot_be_reused(tmp_path, operation):
    method = create_method(name="longmemory_v1", state_path=tmp_path / "closed.db")
    method.close()
    arguments = {"observe": (event(),), "recall": ("问题",), "wait_until_ready": ()}
    with pytest.raises(RuntimeError, match="已经关闭"):
        getattr(method, operation)(*arguments[operation])


@pytest.mark.parametrize("entrypoint", ["method", "chat", "xiaozhi"])
def test_unknown_method_does_not_create_directory(tmp_path, entrypoint):
    path = tmp_path / "never-created" / "state.db"
    with pytest.raises(ValueError):
        if entrypoint == "method":
            create_method(name="memrl", state_path=path)
        elif entrypoint == "chat":
            build_application(database_path=path, method_name="memrl")
        else:
            with open_memory_service(path, method_name="memrl"):
                pytest.fail("Unsupported method must not open")
    assert not path.parent.exists()


def test_neutral_contract_has_no_domain_or_storage_imports():
    tree = ast.parse(Path(contracts.__file__).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(module in {"dataclasses", "datetime", "typing"} for module in imports)


@pytest.mark.parametrize("changes", [
    {"event_id": " "}, {"content": " "}, {"role": "tool"},
    {"occurred_at": datetime(2026, 1, 1)}, {"session_id": ""},
])
def test_event_validation(changes):
    values = dict(event_id="x", role="user", content="合成内容", occurred_at=NOW)
    values.update(changes)
    with pytest.raises(ValueError):
        MemoryEvent(**values)


def test_empty_operations_and_invalid_query_do_not_add_messages(tmp_path):
    path = tmp_path / "empty.db"
    method = create_method(name="longmemory_v1", state_path=path)
    try:
        assert method.observe(event(content="你好")).writes == ()
        before = rows(path)
        with pytest.raises(ValueError):
            method.recall(" ")
        assert rows(path) == before
    finally:
        method.close()
