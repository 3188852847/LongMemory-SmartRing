"""仅合成客户端/新临时目录；不导入外部 SDK，不访问个人库。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
import sqlite3

import pytest

from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from longmemory.methods.hy_memory.method import HyMemoryMethod, HyAdministration
from longmemory.methods.hy_memory.administration import HyManagementConflict, HyManagementUncertain
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE, HyResponseError
from longmemory.methods.hy_memory.settings import HySettings


class Client:
    def __init__(self, root):
        self.state = SimpleNamespace(root=root, _lease=object())
        self.row = {"memory_id": "synthetic-item", "content": "合成用户喜欢茶", "layer": "l2_fact",
            "user_id": "synthetic-user", "agent_id": "synthetic-agent", "status": "ACTIVE",
            "source": SOURCE_NAMESPACE, "meta": [{"namespace": SOURCE_NAMESPACE, "source_event_ids": ["synthetic-source"]}]}
        self.calls = []
        self.fail_after_write = False

    def management_capabilities(self):
        return {"protocol": 1, "profile": False, "exclusive_user_profile": False,
            "history": True, "update": True, "delete": True}

    def get(self, **kwargs):
        return dict(self.row) if self.row and kwargs["memory_id"] == self.row["memory_id"] else None

    def history(self, **kwargs):
        return [{"memory_id": kwargs["memory_id"], "event": "UPDATE", "old_memory": "合成旧值", "new_memory": "合成新值", "created_at": None, "secret_extra": "不应透传"}]

    def search(self, *args, **kwargs):
        return {"request_id": "synthetic-recall", "memories": {"normal": [dict(self.row)] if self.row else [], "schema": [], "proactive": []}}

    def list_memories(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"vdb": {"memories": [self.row] if self.row else [], "total": int(bool(self.row))}}

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        self.row["content"] = kwargs["content"]
        if self.fail_after_write:
            raise RuntimeError("synthetic-private-error")
        return {"success": True, "memory_id": kwargs["memory_id"]}

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        self.row = None
        return {"success": True, "deleted_count": 1}

    def close(self): pass


def setup(root, *, enabled=True):
    client = Client(root)
    method = HyMemoryMethod(settings=HySettings(user_id="synthetic-user", agent_id="synthetic-agent"), client_factory=lambda: client)
    return client, HyAdministration(method, serialized_writes=enabled)


def correction(admin, *, revision=None, request_id=None, content="合成用户喜欢水"):
    request_id = request_id or str(uuid4())
    return {"item_id": "synthetic-item", "request_id": request_id,
        "expected_revision": revision or admin.get_item("synthetic-item").revision,
        "source": MemoryEvent("hy-management:" + request_id, "user", content, datetime.now(UTC)), "content": content}


def test_protocol_default_read_only_and_original_export(tmp_path):
    # tmp_path 为 pytest 唯一临时目录；无持久正文副本。
    client, admin = setup(tmp_path, enabled=False)
    workspace = admin.extension("workspace")
    assert not workspace["correction"] and not workspace["deletion"]
    assert not workspace["native_atomic_revision"]
    assert workspace["history"] and not workspace["profile"]
    with pytest.raises(UnsupportedCapabilityError):
        admin.extension("correct", **correction(admin))
    assert not (tmp_path / "management.sqlite3").exists()


def test_single_correction_readback_source_and_persistent_replay(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    result = admin.extension("correct", **args)
    assert result["state"] == "completed" and not result["replayed"]
    assert admin.get_item("synthetic-item").content == args["content"]
    operations = admin.extension("operations", item_id="synthetic-item")
    assert operations["items"][0]["source_event_id"] == args["source"].event_id
    assert "content" not in operations["items"][0]
    assert admin.extension("correct", **args)["replayed"]
    reopened = HyAdministration(admin.method, serialized_writes=True)
    assert reopened.extension("correct", **args)["replayed"]
    assert sum(name == "update" for name, _ in client.calls) == 1
    recalled = admin.method.recall("合成查询")
    assert recalled.retrieved[0].source_event_ids == ("synthetic-source", args["source"].event_id)


def test_conflict_before_sdk_and_concurrent_revision_is_serialized(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(admin.extension, "correct", **correction(admin, revision=args["expected_revision"], content=value)) for value in ("合成新值一", "合成新值二")]
    results = []
    for future in futures:
        try: results.append(future.result()["state"])
        except HyManagementConflict: results.append("conflict")
    assert sorted(results) == ["completed", "conflict"]
    assert sum(name == "update" for name, _ in client.calls) == 1


def test_partial_commit_is_uncertain_never_retried_even_with_new_request(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    client.fail_after_write = True
    with pytest.raises(HyManagementUncertain, match="outcome_uncertain"):
        admin.extension("correct", **args)
    assert admin.get_item("synthetic-item").content == args["content"]
    for other in (args, correction(admin, content="合成又一值")):
        with pytest.raises(HyManagementUncertain): admin.extension("correct", **other)
    assert sum(name == "update" for name, _ in client.calls) == 1
    assert admin.extension("operations")["items"][0]["error_code"] == "hy_management_outcome_uncertain"
    recalled = admin.method.recall("合成查询")
    assert recalled.context == "" and recalled.retrieved == ()
    assert recalled.warning_code == "hy_management_uncertain_items_excluded"


def test_restart_running_becomes_uncertain_and_payload_conflict(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    admin.extension("correct", **args)
    with sqlite3.connect(tmp_path / "management.sqlite3") as db:
        db.execute("UPDATE operations SET state='running'")
    reopened = HyAdministration(admin.method, serialized_writes=True)
    assert reopened.extension("operations")["items"][0]["state"] == "uncertain"
    with pytest.raises(HyManagementConflict, match="request_conflict"):
        reopened.extension("correct", **{**args, "content": "合成不同载荷", "source": MemoryEvent(args["source"].event_id, "user", "合成不同载荷", datetime.now(UTC))})


def test_delete_is_single_item_replay_and_sources_preserved(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    args.pop("content")
    args["source"] = MemoryEvent(args["source"].event_id, "user", "删除这条记忆：synthetic-item", datetime.now(UTC))
    assert admin.extension("delete", **args)["platform_sources_preserved"]
    assert client.row is None
    assert admin.extension("delete", **args)["replayed"]
    assert sum(name == "delete" for name, _ in client.calls) == 1


@pytest.mark.parametrize("field,value", [("user_id", "foreign"), ("agent_id", "foreign"), ("source", "foreign")])
def test_scope_rejected_before_management(tmp_path, field, value):
    client, admin = setup(tmp_path)
    client.row[field] = value
    with pytest.raises(UnsupportedCapabilityError): admin.get_item("synthetic-item")


def test_unknown_sources_and_time_are_not_invented_and_history_is_projected(tmp_path):
    client, admin = setup(tmp_path)
    client.row.pop("meta")
    item = admin.get_item("synthetic-item")
    assert item.source_event_ids is None and item.recorded_at is None
    history = admin.extension("history", item_id=item.item_id)
    assert not history["recording_complete"] and "secret_extra" not in history["items"][0]
    client.row["gmt_created"] = float('nan')
    with pytest.raises(HyResponseError): admin.get_item(item.item_id)


def test_sdk_vdb_source_is_transport_and_revision_excludes_read_telemetry(tmp_path):
    client, admin = setup(tmp_path)
    client.row["source"] = "vdb"
    first = admin.get_item("synthetic-item")
    client.row.update(request_id="another-read", elapsed_ms=9.2)
    assert admin.get_item("synthetic-item").revision == first.revision
    client.row["custom"] = {"changed": True}
    assert admin.get_item("synthetic-item").revision != first.revision


def test_assistant_source_and_nonmanageable_layer_rejected(tmp_path):
    client, admin = setup(tmp_path)
    args = correction(admin)
    args["source"] = MemoryEvent(args["source"].event_id, "assistant", args["content"], datetime.now(UTC))
    with pytest.raises(ValueError): admin.extension("correct", **args)
    client.row["layer"] = "l0_basic_info"
    with pytest.raises(UnsupportedCapabilityError): admin.extension("correct", **correction(admin))
    assert not any(name == "update" for name, _ in client.calls)


def test_exclusive_owner_required_and_foreign_history_rejected(tmp_path):
    client, admin = setup(tmp_path)
    client.state._lease = None
    with pytest.raises(UnsupportedCapabilityError): admin.extension("operations")
    client.history = lambda **kwargs: [{"memory_id": "foreign-item"}]
    with pytest.raises(HyResponseError): admin.extension("history", item_id="synthetic-item")
