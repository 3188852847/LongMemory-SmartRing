"""真实未初始化方法对象，底层语义只读不能触发factory/子进程/SDK/SQLite。"""

from threading import Event,Thread
import sqlite3
import subprocess
import sys

import pytest

from longmemory.methods.hy_memory.administration import HyAdministration
from longmemory.methods.hy_memory.method import HyMemoryMethod
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.semantic import SemanticBusy
from longmemory.methods.hy_memory.settings import HySettings


@pytest.mark.parametrize("operation",["semantic_status","semantic_task"])
@pytest.mark.parametrize("through_admin",[False,True])
@pytest.mark.parametrize("closed",[False,True])
def test_cold_semantic_reads_refuse_without_any_initialization(tmp_path,monkeypatch,operation,through_admin,closed):
    calls={"factory":0,"subprocess":0,"sqlite":0}
    def popen(*args,**kwargs):
        calls["subprocess"]+=1
        raise AssertionError("cold read started subprocess")
    def connect(*args,**kwargs):
        calls["sqlite"]+=1
        raise AssertionError("cold read opened SQLite")
    def factory():
        calls["factory"]+=1
        subprocess.Popen(["must-not-start"])
    monkeypatch.setattr(subprocess,"Popen",popen)
    monkeypatch.setattr(sqlite3,"connect",connect)
    before={key for key in sys.modules if key=="hy_memory" or key.startswith("hy_memory.")}
    method=HyMemoryMethod(settings=HySettings(user_id="ab-cold",semantic_layers_enabled=True),client_factory=factory)
    if closed:
        method.close()
    call=HyAdministration(method).extension if through_admin else method.sdk_call
    with pytest.raises(HyResponseError,match="^hy_semantic_unavailable$"):
        call(operation,**({"task_id":"unknown"} if operation=="semantic_task" else {}))
    assert calls=={"factory":0,"subprocess":0,"sqlite":0}
    assert method._client is None and method._bridge is None
    assert list(tmp_path.iterdir())==[]
    assert before=={key for key in sys.modules if key=="hy_memory" or key.startswith("hy_memory.")}


@pytest.mark.parametrize("operation",["semantic_status","semantic_task"])
@pytest.mark.parametrize("through_admin",[False,True])
def test_busy_semantic_read_does_not_wait_or_initialize(operation,through_admin):
    calls=[]
    method=HyMemoryMethod(settings=HySettings(user_id="ab-cold"),client_factory=lambda:calls.append(True))
    held,release=Event(),Event()
    def hold():
        with method._lock:
            held.set()
            release.wait(2)
    thread=Thread(target=hold)
    thread.start()
    try:
        assert held.wait(1)
        call=HyAdministration(method).extension if through_admin else method.sdk_call
        with pytest.raises(SemanticBusy,match="hy_semantic_status_busy"):
            call(operation,**({"task_id":"unknown"} if operation=="semantic_task" else {}))
        assert not calls and method._client is None
    finally:
        release.set();thread.join(timeout=2)
