from contextlib import contextmanager,nullcontext
from dataclasses import replace
from threading import Event
from time import monotonic,sleep
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory.background import BackgroundLane
from longmemory.methods.hy_memory.semantic import SemanticCoordinator
from longmemory.methods.hy_memory.settings import Endpoint,HySettings
from longmemory.methods.hy_memory.worker import RequestBudget


def settings():
    endpoint=Endpoint("http://127.0.0.1:19765/hy/v1","synthetic","local-owner-token",True)
    return HySettings(user_id="ab-background",llm=endpoint,embedding=endpoint,semantic_layers_enabled=True,
        network_authorized=True,managed_gateway=True,provider_identity="a"*64,max_external_requests=10,
        background_priority_enabled=True)


def until(predicate):
    limit=monotonic()+3
    while monotonic()<limit:
        if predicate():
            return
        sleep(.01)
    raise AssertionError("background synthetic timeout")


def test_background_is_runtime_only_and_alias_is_not_arbitrary():
    current=settings()
    assert current.identity()==replace(current,background_priority_enabled=False).identity()
    assert current==HySettings.from_wire(current.wire())
    for values in ({"managed_gateway":False},{"semantic_layers_enabled":False},{"network_authorized":False},
            {"llm":replace(current.llm,base_url="http://127.0.0.1:19765/other/v1")}):
        with pytest.raises(ValueError):
            replace(current,**values)
    budget=RequestBudget(current)
    budget.claim("http://127.0.0.1:19765/hy-background/v1/chat/completions")
    assert budget.report()["local_gateway_requests"]==1
    for url in ("http://127.0.0.1:19766/hy-background/v1/chat/completions",
            "http://127.0.0.1:19765/hy-background/v1/embeddings",
            "http://127.0.0.1:19765/hy-background/v1/admission",
            "http://127.0.0.1:19765/hy-background/v1/chat/completions?redirect=x"):
        with pytest.raises(RuntimeError,match="network_denied"):
            budget.claim(url)
    assert budget.report()["local_gateway_requests"]==1


def test_background_context_changes_only_own_llm_route():
    import asyncio
    lane=BackgroundLane(settings())
    async def request(background,path):
        with lane.operation() if background else nullcontext():
            await asyncio.sleep(0)
            req=SimpleNamespace(url="http://127.0.0.1:19765/hy/v1/"+path,content=b"same-body")
            lane.route(req)
            assert req.content==b"same-body"
            return str(req.url)
    async def run():
        return await asyncio.gather(request(True,"chat/completions"),request(False,"chat/completions"),request(True,"embeddings"))
    assert asyncio.run(run())==["http://127.0.0.1:19765/hy-background/v1/chat/completions",
        "http://127.0.0.1:19765/hy/v1/chat/completions","http://127.0.0.1:19765/hy/v1/embeddings"]


@pytest.mark.parametrize("value,eligible",[
    ({"version":1,"eligible":True,"reason_code":None},True),
    ({"version":1,"eligible":False,"reason_code":"model_busy"},False),
    ({"version":1,"eligible":True,"reason_code":"model_busy"},False),
    ({"version":True,"eligible":True,"reason_code":None},False),
    ({"version":1,"eligible":False,"reason_code":{"untrusted":True}},False),
    ({"version":1,"eligible":True,"reason_code":None,"lease":"invented"},False)])
def test_advice_is_authenticated_exact_contract_without_reservation(monkeypatch,value,eligible):
    import json
    import sys
    seen=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs=={"timeout":2,"trust_env":False,"follow_redirects":False}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,*,headers):
            seen.append(("GET",url,headers["Authorization"]))
            return SimpleNamespace(status_code=200,content=json.dumps(value).encode(),json=lambda:value)
    monkeypatch.setitem(sys.modules,"httpx",SimpleNamespace(Client=Client,HTTPError=ConnectionError))
    lane=BackgroundLane(settings())
    assert lane.eligible() is eligible
    assert seen==[("GET","http://127.0.0.1:19765/hy-background/v1/admission","Bearer local-owner-token")]
    assert lane.snapshot()["admission_reserves_model"] is False


def test_advice_busy_keeps_pending_and_management_work_lock_free(tmp_path):
    ready,checked=Event(),Event()
    calls=[]
    class Lane:
        def eligible(self):
            assert not owner._work.locked()
            assert owner.task("wait")["state"]=="pending"
            checked.set()
            return ready.is_set()
        @contextmanager
        def operation(self):
            assert ready.is_set()
            yield
    owner=SemanticCoordinator(SimpleNamespace(evolve=lambda **kwargs:calls.append(kwargs) or {"success":True}),
        settings(),tmp_path,background=Lane())
    try:
        owner.enqueue("wait")
        assert checked.wait(2)
        assert owner.status()["task_counts"]=={"pending":1} and not calls
        assert owner._work.acquire(blocking=False)
        owner._work.release()
        ready.set()
        until(lambda:owner.task("wait")["state"]=="completed")
        assert len(calls)==1
    finally:
        owner.close()
