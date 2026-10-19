from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from longmemory.bootstrap import assemble_backend, build_backend_runtime
from longmemory.methods.backend_contracts import StateResource, ManagementCapabilities
from longmemory.methods.contracts import MemoryEvent, MethodCapabilities, MemorySupport


class Engine:
    name, implementation_version = "synthetic_extension", "1"
    capabilities = MethodCapabilities(session_metadata=True)
    def wait_until_ready(self): pass
    def close(self): pass
    def observe(self, event): pytest.fail("管理来源不得通过observe二次提取")
    def recall(self, query): return MemorySupport("test", "", ())


class Admin:
    extension_namespace = "hy_memory"
    capabilities = ManagementCapabilities()
    def __init__(self): self.sources = []
    def extension(self, operation, **arguments):
        if "source" in arguments: self.sources.append(arguments["source"])
        return {"operation": operation}


def setup(tmp_path):
    admin = Admin()
    assembly = assemble_backend(method=Engine(), resources=(StateResource("e", tmp_path / "e", "file"),),
        source_path=tmp_path / "sources.db", create_sources=True, management=admin)
    return build_backend_runtime(assembly), admin


def values(role="user"):
    request = str(uuid4())
    return {"request_id": request, "item_id": "synthetic-item", "content": "合成纠正内容",
        "expected_revision": "a" * 64, "source": MemoryEvent("hy-management:" + request,
            role, "合成纠正内容", datetime.now(UTC), "original-session")}


def test_extension_replay_reuses_original_source_time_session_without_observe(tmp_path):
    runtime, admin = setup(tmp_path)
    try:
        args = values()
        runtime.administer_extension("hy_memory", "correct", **args)
        runtime.administer_extension("hy_memory", "correct", **(args | {"source": replace(args["source"],
            occurred_at=args["source"].occurred_at + timedelta(days=1), session_id=None)}))
        assert admin.sources == [args["source"], args["source"]]
        assert len(runtime._method.journal.events()) == 1
        assert runtime.source_status(args["source"].event_id)["state"] == "archived"
        with pytest.raises(ValueError, match="source_conflict"):
            runtime.administer_extension("hy_memory", "correct", **(args | {"content": "另一个正文",
                "source": replace(args["source"], content="另一个正文")}))
    finally: runtime.close()


def test_extension_permissions_namespace_roles_and_closed_are_guarded(tmp_path):
    runtime, admin = setup(tmp_path)
    for namespace, operation in (("unknown", "workspace"), ("hy_memory", "sdk_call")):
        with pytest.raises(ValueError): runtime.administer_extension(namespace, operation)
    with pytest.raises(ValueError, match="user_source"):
        runtime.administer_extension("hy_memory", "correct", **values("assistant"))
    runtime.configure(write_enabled=False, use_enabled=True)
    with pytest.raises(ValueError, match="write_paused"):
        runtime.administer_extension("hy_memory", "correct", **values())
    assert runtime._method.journal.events() == ()
    assert runtime.administer_extension("hy_memory", "workspace")["operation"] == "workspace"
    runtime.close()
    with pytest.raises(RuntimeError): runtime.administer_extension("hy_memory", "workspace")
