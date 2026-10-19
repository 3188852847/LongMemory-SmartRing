from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from time import time

import pytest

from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.budget import BudgetStopped, PricePolicy, SharedBudget
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.settings import Endpoint


def ledger(tmp_path):
    return SharedBudget(tmp_path/"budget.db",policy=PricePolicy(expires_at_unix=time()+3600),create=True)


def test_shared_ledger_not_reset_on_reopen_or_worker(tmp_path):
    budget=ledger(tmp_path)
    aid=budget.reserve("hy")
    with pytest.raises(BudgetStopped):SharedBudget(budget.path).reserve("answer")
    budget.finish(aid,{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120},successful=True)
    reopened=SharedBudget(budget.path)
    assert reopened.report()["held_or_settled_upper_micro_cny"]==360
    second=reopened.reserve("baseline")
    reopened.finish(second,None,successful=False)
    assert reopened.report()["unknown_or_inflight"]==1
    with pytest.raises(BudgetStopped):budget.reserve("hy")


@pytest.mark.parametrize("usage",[None,{}, {"prompt_tokens":False,"completion_tokens":0,"total_tokens":0},
    {"prompt_tokens":1,"completion_tokens":2,"total_tokens":0},
    {"prompt_tokens":2_097_153,"completion_tokens":1,"total_tokens":2_097_154}])
def test_unknown_or_invalid_usage_keeps_full_reservation(tmp_path,usage):
    budget=ledger(tmp_path);aid=budget.reserve("probe")
    budget.finish(aid,usage,successful=True)
    assert budget.report()["held_or_settled_upper_micro_cny"]==8_388_608


def test_concurrent_reservation_cannot_exceed_total_limit(tmp_path):
    budget=ledger(tmp_path)
    def attempt(_):
        try:return SharedBudget(budget.path).reserve("hy")
        except BudgetStopped:return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(value is not None for value in pool.map(attempt,range(8)))==1
    assert budget.report()["held_or_settled_upper_micro_cny"]<=10_000_000


def test_gateway_counts_all_roles_and_rejects_server_tools(tmp_path):
    budget=ledger(tmp_path)
    settings=ModelSettings(provider="openai_compatible",base_url="https://api.deepseek.com",api_key="synthetic-only",model="deepseek-v4-flash")
    class Encoder:identity="synthetic-encoder"
    sent=[]
    def remote(body):
        payload=json.loads(body);sent.append(payload)
        return 200,json.dumps({"choices":[{"message":{"content":"合成"},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":100,"completion_tokens":10,"total_tokens":110}}).encode()
    gateway=ModelGateway(settings=settings,budget=budget,encoder=Encoder(),currency_verified=True,remote=remote)
    try:
        for role in ("hy","baseline","answer"):
            assert gateway.complete(role,{"model":settings.model,"max_tokens":512,"messages":[{"role":"system","content":"合成测试"}]})[0]==200
        assert budget.report()["attempt_count"]==3
        assert all(item["thinking"]=={"type":"disabled"} for item in sent)
        with pytest.raises(ValueError):gateway.complete("hy",{"model":settings.model,"max_tokens":512,"tools":[{"type":"web_search"}]})
    finally:gateway.server.server_close()


def test_http_exception_only_for_explicit_loopback():
    with pytest.raises(ValueError):Endpoint("http://external.example/v1","m","k",True)
    with pytest.raises(ValueError):Endpoint("http://127.0.0.1:8767/v1","m","k",True)
    assert Endpoint("http://127.0.0.1:29347/v1","m","k",True).allow_loopback_http
