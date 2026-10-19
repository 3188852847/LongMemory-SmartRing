"""管理范围与拒绝；真实 SDK 副作用另在禁网集成测试验证。"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory.management_rpc import ManagementRPC, HyManagementDenied
from longmemory.methods.hy_memory.sdk_bridge import SDK_VERSION, SOURCE_NAMESPACE, HyResponseError
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.worker import ProtocolService, RequestBudget


SETTINGS = HySettings(user_id="synthetic-management", model_mode="synthetic_transport",
    management_writes_enabled=True)


class Client:
    def __init__(self):
        self.calls = []
        self.row = {"memory_id":"fact-1", "content":"原事实", "user_id":SETTINGS.user_id,
            "agent_id":SETTINGS.agent_id, "source":"vdb", "layer":"l2_fact", "status":"active",
            "is_latest":True, "supersedes":[], "superseded_by":[], "meta":[{"namespace":SOURCE_NAMESPACE, "role":"user",
                "source_event_ids":["event-1"]}]}
        self.history_rows = []

    def get(self, memory_id):
        self.calls.append(("get", memory_id))
        return deepcopy(self.row)

    def update(self, *, memory_id, content):
        self.calls.append(("update", memory_id, content))
        self.row["content"] = content
        return {"success":True, "memory_id":memory_id}

    def history(self, *, memory_id):
        self.calls.append(("history", memory_id))
        return self.history_rows

    def delete(self, *, memory_id):
        self.calls.append(("delete",memory_id));self.row=None
        return {"success":True,"deleted_count":1}


def manager(settings=SETTINGS):
    client=Client()
    budget=SimpleNamespace(actual_sdk_version=SDK_VERSION, management_update_verified=True)
    return ManagementRPC(client,settings,budget),client


def test_capabilities_require_audited_sdk_config_and_explicit_permissions():
    rpc,_=manager()
    caps=rpc.capabilities()
    assert caps["protocol"]==1 and caps["history"] and caps["update"]
    assert caps["delete"] and not caps["profile"] and not caps["exclusive_user_profile"]
    assert "evolution" in caps["limitations"]["delete"]
    assert "user_agent_source" in caps["limitations"]["profile"]
    assert not manager(replace(SETTINGS,management_writes_enabled=False))[0].capabilities()["update"]
    assert not manager(replace(SETTINGS,model_mode="disabled"))[0].capabilities()["update"]
    rpc.budget.management_update_verified=False
    assert not rpc.capabilities()["update"]
    rpc.budget.actual_sdk_version="unknown"
    assert not rpc.capabilities()["history"]


def test_management_permission_is_runtime_policy_not_persistent_identity():
    assert SETTINGS.identity()==replace(SETTINGS,management_writes_enabled=False).identity()
    assert HySettings.from_wire(SETTINGS.wire())==SETTINGS
    assert SETTINGS.identity()==replace(SETTINGS,management_exclusive_profile=True).identity()
    with pytest.raises(ValueError):
        replace(SETTINGS,management_writes_enabled=1)


@pytest.mark.parametrize("operation,arguments", [
    ("history",{"memory_id":"fact-1","user_id":"foreign"}),
    ("update",{"memory_id":"fact-1","content":"新事实","expected_revision":"fake"}),
    ("delete",{"memory_id":"fact-1","delete_all":True}),
    ("management_capabilities",{"workspace":"other"}),
    ("delete_all",{}),
    ("history",{"memory_id":""}),
    ("history",{"memory_id":"../data.db"}),
    ("history",{"memory_id":False}),
    ("history",{"memory_id":"id\nother"}),
    ("update",{"memory_id":"fact-1","content":" "}),
    ("update",{"memory_id":"fact-1","content":"x"*1001}),
])
def test_invalid_arguments_never_enter_sdk(operation,arguments):
    rpc,client=manager()
    with pytest.raises(HyManagementDenied):
        rpc.execute(operation,arguments)
    assert client.calls==[]


@pytest.mark.parametrize("change", [
    {"memory_id":"other"}, {"user_id":"other"}, {"agent_id":"other"},
    {"source":"graph"}, {"meta":None},
    {"meta":[{"namespace":"other","role":"user","source_event_ids":["x"]}]},
    {"meta":[{"namespace":SOURCE_NAMESPACE,"role":"assistant","source_event_ids":["x"]}]},
])
def test_foreign_or_unknown_scope_never_enters_history_or_update(change):
    for operation in ("history","update"):
        rpc,client=manager();client.row.update(change)
        args={"memory_id":"fact-1",**({"content":"新事实"} if operation=="update" else {})}
        with pytest.raises(HyManagementDenied):rpc.execute(operation,args)
        assert client.calls==[("get","fact-1")]


@pytest.mark.parametrize("change", [{"layer":"l0_basic_info"},{"layer":"l1_raw"},
    {"status":"shadow"},{"is_latest":False}])
def test_non_current_or_reserved_layers_cannot_be_updated(change):
    rpc,client=manager();client.row.update(change)
    with pytest.raises(HyManagementDenied):rpc.execute("update",{"memory_id":"fact-1","content":"新事实"})
    assert client.calls==[("get","fact-1")]


def test_single_update_and_history_keep_sdk_shape_and_old_meta():
    rpc,client=manager();before=deepcopy(client.row["meta"])
    assert rpc.execute("update",{"memory_id":"fact-1","content":"明确纠正"})=={"success":True,"memory_id":"fact-1"}
    assert client.row["meta"]==before
    assert rpc.execute("history",{"memory_id":"fact-1"})==[]
    assert [x[0] for x in client.calls]==["get","update","get","history"]
    client.history_rows=[{"memory_id":"other", "old_memory":"do not disclose"}]
    with pytest.raises(HyResponseError):rpc.execute("history",{"memory_id":"fact-1"})


@pytest.mark.parametrize("links", [
    {"supersedes":["old"]}, {"superseded_by":["new"]},
    {"supersedes":["old"],"superseded_by":["new"]}, {"supersedes":None},
])
def test_delete_chain_head_middle_tail_or_unknown_links_never_enters_sdk(links):
    rpc,client=manager();client.row.update(links)
    with pytest.raises(HyManagementDenied):rpc.execute("delete",{"memory_id":"fact-1"})
    assert client.calls==[("get","fact-1")]


def test_delete_isolated_node_returns_unmodified_sdk_result():
    rpc,client=manager()
    assert rpc.execute("delete",{"memory_id":"fact-1"})=={"success":True,"deleted_count":1}
    assert client.calls==[("get","fact-1"),("delete","fact-1")]


def test_sdk_partial_failure_has_one_attempt_and_propagates_to_worker_envelope():
    rpc,client=manager()
    def partial(**kwargs):
        client.calls.append(("partial",));client.row["content"]="partially committed"
        raise TimeoutError("private-body")
    client.update=partial
    with pytest.raises(TimeoutError):rpc.execute("update",{"memory_id":"fact-1","content":"明确纠正"})
    assert client.calls==[("get","fact-1"),("partial",)]


def test_protocol_rejects_arbitrary_operations_and_foreign_profile_user():
    client=Client()
    def factory(settings,workspace,*,create):return client,RequestBudget(settings)
    service=ProtocolService(factory)
    service.execute("initialize",{"settings":SETTINGS.wire(),"workspace":"unused-fixture","create":True})
    for operation,args in [("delete_all",{}),("get_user_profile",{"user_id":"foreign"})]:
        with pytest.raises(ValueError):service.execute(operation,args)
    assert not service.execute("management_capabilities",{})["update"]
    assert client.calls==[]
    with pytest.raises(ValueError,match="owner_scope_invalid"):
        service.execute("add",{"user_id":"other","agent_id":SETTINGS.agent_id,"source":SOURCE_NAMESPACE})


def test_update_transport_rejects_llm_before_network_budget_claim():
    budget=RequestBudget(SETTINGS);budget.operation="update"
    with pytest.raises(RuntimeError,match="management_llm_denied"):
        budget.check_management_request("https://blocked.invalid/v1/chat/completions")
    budget.check_management_request("https://blocked.invalid/v1/embeddings")
    assert budget.management_llm_attempts_blocked==1 and budget.management_embedding_attempts==1
    assert budget.attempts==0


def test_profile_flag_or_method_alone_does_not_prove_exclusive_scope(tmp_path):
    rpc,client=manager(replace(SETTINGS,management_exclusive_profile=True))
    client.get_user_profile=lambda **kwargs: {"profile":None}
    assert not rpc.capabilities()["profile"]
    rpc.budget.management_profile_scope_proven=True
    rpc.budget.management_workspace=tmp_path
    assert not rpc.capabilities()["profile"]  # 没有独占 owner 锁仍不得开放。
    from longmemory.methods.hy_memory.assembly import HyState
    state=HyState(tmp_path/'owned',rpc.settings,create=True)
    state.acquire();rpc.budget.management_workspace=state.root
    try:
        assert rpc.capabilities()["profile"] and rpc.capabilities()["exclusive_user_profile"]
    finally:state.release()
    assert not rpc.capabilities()["profile"]
