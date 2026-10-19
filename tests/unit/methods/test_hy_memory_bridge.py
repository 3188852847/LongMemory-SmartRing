from datetime import UTC, datetime
from importlib import metadata

import pytest

from longmemory.methods.hy_memory import preflight
from longmemory.methods.hy_memory.sdk_bridge import (
    HyResponseError, HySdkBridge, SOURCE_NAMESPACE, normalize_search,
)


def row(**updates):
    return {"memory_id": "m-1", "content": "合成事实", "layer": "l2_fact", "score": 0.7,
            "meta": [{"namespace": SOURCE_NAMESPACE, "source_event_ids": ["event-1"]}], **updates}


def response(**updates):
    return {"request_id": "search-1", "memories": {"normal": [row()], "schema": [], "proactive": []}, **updates}


class FakeClient:
    """只验证参数与失败传播，完全没有实现 Hy 提取/持久化。"""
    def __init__(self):
        self.calls = []
        self.write_response = {"success": True, "memory_id": "raw-1", "request_id": "event-1"}

    def add(self, data, **kwargs):
        self.calls.append(("add", data, kwargs))
        return self.write_response

    def search(self, query, **kwargs):
        self.calls.append(("search", query, kwargs))
        return response()

    def get_user_profile(self, **kwargs):
        self.calls.append(("profile", kwargs))
        return {"profile": row(layer="l0_basic_info", score=None)}

    def close(self):
        self.calls.append(("close",))


def add(bridge, **updates):
    return bridge.add_event(**{"event_id": "event-1", "role": "user", "content": "合成内容",
                              "occurred_at": datetime(2026, 1, 1, tzinfo=UTC), "session_id": "session-1", **updates})


def test_role_time_source_and_session_preserved():
    client = FakeClient()
    result = add(HySdkBridge(client, user_id="synthetic-1"), role="assistant")
    assert result.derived_memory_ids == ()
    _, messages, options = client.calls[0]
    assert messages == [{"role": "assistant", "content": "合成内容"}]
    assert options["memory_at"].tzinfo is UTC
    assert options["session_id"] == "session-1"
    assert options["scene"] == "chat"
    assert "metadata" not in options
    assert options["meta"]["source_event_ids"] == ["event-1"]


def test_search_scopes_cross_session_and_no_proactive():
    client = FakeClient()
    support = HySdkBridge(client, user_id="synthetic-1").search("合成问题")
    options = client.calls[0][2]
    assert options["user_ids"] == ["synthetic-1"]
    assert options["include_sources"] == [SOURCE_NAMESPACE]
    assert options["search_mode"] == "default"
    assert options["intention_limit"] == options["schema_limit"] == 0
    assert "session_ids" not in options
    assert support.items[0].source_event_ids == ("event-1",)
    assert support.profile is None
    assert len(client.calls) == 1


def test_profile_is_separate_and_opt_in():
    client = FakeClient()
    support = HySdkBridge(client, user_id="synthetic-1").search("问题", include_profile=True)
    assert support.profile.channel == "profile"
    assert client.calls[1] == ("profile", {"user_id": "synthetic-1"})


def test_unknown_provenance_not_guessed_from_metadata():
    support = normalize_search(response(memories={"normal": [row(meta=None, metadata={"source_event_ids": ["fake"]})], "schema": [], "proactive": []}))
    assert support.items[0].source_event_ids is None


@pytest.mark.parametrize("bad", [[], {"request_id":"x", "memories":{"profile":[],"normal":[],"proactive":[]}}, {"success":False}])
def test_bad_shape_fails_closed(bad):
    with pytest.raises(HyResponseError):
        normalize_search(bad)


@pytest.mark.parametrize("updates", [{"content":""}, {"role":"tool"}, {"session_id":""}, {"occurred_at":datetime(2026, 1, 1)}])
def test_invalid_event_does_not_call_client(updates):
    client = FakeClient()
    with pytest.raises((ValueError, HyResponseError)):
        add(HySdkBridge(client, user_id="synthetic-1"), **updates)
    assert not client.calls


def test_failed_add_not_retried_or_declared_archived():
    client = FakeClient()
    client.write_response = {"success":False, "error_message":"sensitive external body"}
    with pytest.raises(HyResponseError, match="hy_add_failed_state_unknown") as exc:
        add(HySdkBridge(client, user_id="synthetic-1"))
    assert "sensitive" not in str(exc.value)
    assert len(client.calls) == 1


def test_transport_exception_not_retried():
    client = FakeClient()
    def fail(*args, **kwargs):
        client.calls.append(("failed_once",))
        raise TimeoutError("transport")
    client.add = fail
    with pytest.raises(HyResponseError, match="hy_add_transport_failed_state_unknown"):
        add(HySdkBridge(client, user_id="synthetic-1"))
    assert len(client.calls) == 1


def test_bridge_makes_no_sdk_idempotency_claim():
    client = FakeClient()
    bridge = HySdkBridge(client, user_id="synthetic-1")
    add(bridge)
    add(bridge)
    assert len(client.calls) == 2  # 最终方法适配器必须另行实现持久重复事件策略。


def test_close_idempotent_and_reuse_refused():
    client = FakeClient()
    bridge = HySdkBridge(client, user_id="synthetic-1")
    bridge.close()
    bridge.close()
    assert client.calls == [("close",)]
    with pytest.raises(RuntimeError, match="closed"):
        bridge.search("问题")


def test_missing_sdk_preflight_does_not_import(monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(preflight.metadata, "version", missing)
    assert preflight.inspect_installation(check_api=True)["status"] == "missing"


def test_wrong_version_rejected_before_import(monkeypatch):
    monkeypatch.setattr(preflight.metadata, "version", lambda name: "2.0.4")
    assert preflight.inspect_installation(check_api=True)["status"] == "version_mismatch"


def test_empty_results_are_not_failure():
    result = normalize_search(response(memories={"normal":[], "schema":[], "proactive":[]}))
    assert result.items == ()
    assert result.elapsed_ms is None


def test_merged_provenance_is_deduplicated():
    result = normalize_search(response(memories={"normal":[row(meta=[
        {"namespace":SOURCE_NAMESPACE, "source_event_ids":["a", "b"]},
        {"namespace":SOURCE_NAMESPACE, "source_event_ids":["b", "c"]},
        {"namespace":"unrelated", "source_event_ids":["d"]},
    ])], "schema":[], "proactive":[]}))
    assert result.items[0].source_event_ids == ("a", "b", "c")


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "0.7"])
def test_invalid_sdk_scores_rejected(bad):
    with pytest.raises(HyResponseError):
        normalize_search(response(memories={"normal":[row(score=bad)], "schema":[], "proactive":[]}))
