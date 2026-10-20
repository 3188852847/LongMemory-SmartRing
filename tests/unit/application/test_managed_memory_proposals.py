"""来源包装边界：候选忙立即回退，关闭/缺能力不借普通召回或来源写入补齐。"""

from threading import Event, Thread
import pytest

from longmemory.application.managed_memory import ManagedMemoryMethod
from longmemory.methods.contracts import MethodCapabilities, UnsupportedCapabilityError


def managed():
    calls = []
    class Journal:
        def close(self): calls.append("journal_close")
        def __getattr__(self, _name): raise AssertionError("candidate touched source journal")
    class Engine:
        name, implementation_version = "synthetic", "synthetic-1"
        capabilities = MethodCapabilities()
        def close(self): calls.append("engine_close")
        def observe(self, *_args, **_kwargs): raise AssertionError("candidate wrote memory")
        def recall(self, *_args, **_kwargs): raise AssertionError("candidate used ordinary recall")
        def wait_until_ready(self): raise AssertionError("candidate lazily initialized engine")
    engine = Engine()
    return ManagedMemoryMethod(engine, Journal()), engine, calls


def operation(method, name):
    return {"snapshot": lambda: method.candidate_snapshot(query_embedding=[1.0], limit=3),
            "validate": lambda: method.candidate_validate(snapshot_token="synthetic-private-token",memory_digest="d"*64),
            "gate": lambda: method.configure_background_writes(write_enabled=False)}[name]()


@pytest.mark.parametrize("name", ["snapshot", "validate"])
def test_busy_wrapper_rejects_before_lock_release_and_never_calls_engine_or_journal(name):
    method, engine, calls = managed()
    entered, release, finished = Event(), Event(), Event()
    outcomes = []
    engine.candidate_snapshot = engine.candidate_validate = lambda **_kwargs: calls.append("unexpected_read")
    def hold():
        with method._lock:
            entered.set()
            assert release.wait(3)
    holder = Thread(target=hold)
    def read():
        try: operation(method,name)
        except RuntimeError as error: outcomes.append(str(error))
        finally: finished.set()
    reader = Thread(target=read)
    try:
        holder.start()
        assert entered.wait(1)
        reader.start()
        assert finished.wait(1), "optional candidate blocked on wrapper instead of returning busy"
        assert outcomes == ["candidate_memory_busy"] and not calls
    finally:
        release.set()
        holder.join(3)
        reader.join(3)
        method.close()
    assert not holder.is_alive() and not reader.is_alive()


@pytest.mark.parametrize("name", ["snapshot", "validate", "gate"])
def test_closed_wrapper_rejects_explicit_capabilities_before_underlying_calls(name):
    method, engine, calls = managed()
    engine.candidate_snapshot = engine.candidate_validate = engine.configure_background_writes = lambda **_kwargs: calls.append("unexpected_call")
    method.close()
    method.close()
    with pytest.raises(RuntimeError, match="已经关闭"):
        operation(method,name)
    assert calls == ["engine_close","journal_close"]


@pytest.mark.parametrize("name", ["snapshot", "validate"])
def test_missing_candidate_capability_never_falls_back_to_recall_or_lazy_initialization(name):
    method, _, calls = managed()
    try:
        with pytest.raises(UnsupportedCapabilityError, match="candidate_memory_unsupported"):
            operation(method,name)
        with pytest.raises(AttributeError):
            method.sdk_call("arbitrary_operation")
        assert not calls
    finally: method.close()


def test_read_status_false_validation_and_write_gate_failure_propagate_without_source_or_retry():
    method, engine, calls = managed()
    unreadable, invalid = {"protocol":1,"read_status":"busy"}, {"protocol":1,"valid":False}
    engine.candidate_snapshot = lambda **kwargs: (calls.append(("snapshot",kwargs)) or unreadable)
    engine.candidate_validate = lambda **kwargs: (calls.append(("validate",kwargs)) or invalid)
    def failed_gate(**kwargs):
        calls.append(("gate",kwargs))
        raise RuntimeError("synthetic_gate_failed")
    engine.configure_background_writes = failed_gate
    try:
        assert operation(method,"snapshot") is unreadable
        assert operation(method,"validate") is invalid
        with pytest.raises(RuntimeError,match="^synthetic_gate_failed$"):
            operation(method,"gate")
        assert calls == [("snapshot",{"query_embedding":[1.0],"limit":3}),
                         ("validate",{"snapshot_token":"synthetic-private-token","memory_digest":"d"*64}),
                         ("gate",{"write_enabled":False})]
    finally: method.close()


def test_old_engine_without_background_gate_remains_compatible_without_inventing_capability():
    method, _, calls = managed()
    try:
        assert method.configure_background_writes(write_enabled=False) is None
        assert not calls
    finally: method.close()
