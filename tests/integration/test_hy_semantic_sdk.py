"""AB: 固定真实SDK的图式归纳/意图读取/管理失效与重开，不代表模型质量。"""

from pathlib import Path
from datetime import UTC, datetime
import hashlib
import json
import os
from time import monotonic, perf_counter, sleep
from uuid import uuid4

import pytest

from longmemory.methods.hy_memory.assembly import assemble_hy_backend, management_primitives_identity
from longmemory.methods.hy_memory.layer_data import validate_result
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.contracts import MemoryEvent


SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason="explicit owner-installed fixed SDK required")
ROOT = Path(__file__).resolve().parents[2]
SETTINGS = HySettings(user_id="ab-semantic-synthetic", agent_id="ab-agent", model_mode="synthetic_transport", semantic_layers_enabled=True,
    include_profile=True)


def open_backend(root, *, create=True, scenario="normal"):
    script = ("import sys;sys.path.insert(0,"+repr(str(ROOT/"src"))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");"
        "from hy_semantic_worker import run;run("+repr(scenario)+")")
    def factory(workspace, *, create):
        from dataclasses import replace
        settings = replace(SETTINGS, management_writes_enabled=True, management_exclusive_profile=True)
        return HyProcessClient(python=SDK, workspace=workspace, settings=settings, create=create,
            command=[str(SDK), "-I", "-X", "utf8", "-B", "-c", script])
    return assemble_hy_backend(settings=SETTINGS, state_directory=root/"engine", source_path=root/"sources.db",
        create=create, client_factory=factory, management_verification={"protocol":2,"sdk_version":"2.0.3",
            "rpc_source_sha256":management_primitives_identity(), "real_sdk_rpc_verified":True,
            "semantic_background_writes":"managed_v1", "derivation_invalidation_verified":True,"read_only_intention_verified":True})


def wait_task(engine, identifier, *, timeout=30):
    until = monotonic()+timeout
    while monotonic()<until:
        row = engine.sdk_call("semantic_task", task_id=identifier)
        if row["state"] not in {"pending", "running"}:
            return row
        sleep(0.05)
    raise AssertionError("AB synthetic task timeout")


def layer(engine, name, *, state="all"):
    result = engine._client.layer_page(layer=name, limit=20, offset=0, state=state)
    return validate_result(result, "layer_page", name)


def test_real_native_evolve_graph_content_sources_restart_and_readonly_intention(tmp_path):
    assembly = open_backend(tmp_path)
    engine = assembly.method.engine
    try:
        assert engine.sdk_call("diagnostics")["actual_sdk_version"] == "2.0.3"
        first = engine.recall("检查资料")
        assert any("未来意图" in row.content for row in first.retrieved)
        assert "expired" not in first.context
        before = layer(engine,"l7_intention")
        assert len(before["items"]) == 2
        assert {r["derivation_state"] for r in before["items"]} == {"stored","expired"}
        engine.sdk_call("semantic_enqueue", task_id="evolve-real")
        task = wait_task(engine,"evolve-real")
        assert task["state"] == "completed", task
        graph = layer(engine,"l6_schema")
        assert graph["generation_state"] == "configured" and graph["coverage"] == "graph_complete"
        assert graph["total"] >= 1, graph
        item = graph["items"][0]
        assert item["source_event_ids"] == ["ab-source-"+str(i) for i in range(4)]
        assert item["semantic_kind"] == "model_inference" and item["execution_authorized"] is False
        support = engine.recall("检查资料")
        assert any("模型归纳" in row.content for row in support.retrieved), support
        assert engine.sdk_call("semantic_enqueue", task_id="evolve-real")["state"] == "completed"
        engine.sdk_call("semantic_enqueue", task_id="expiry", kind="intention_maintenance")
        assert wait_task(engine,"expiry")["state"] == "completed"
        intentions = layer(engine,"l7_intention")
        assert next(row for row in intentions["items"] if "expired" in row["item_id"])["status"] == "archived"
        assert next(row for row in intentions["items"] if "expired" in row["item_id"])["layer"] == "l7_intention"
        assert engine.sdk_call("diagnostics")["external_http_attempts"] == 0
        ids = [row["item_id"] for row in graph["items"]]
        event = MemoryEvent("ab-sdk-extraction", "user", "合成用户计划下周检查资料", datetime.now(UTC), "ab-session")
        assert assembly.method.observe(event).processing_status == "completed"
        extracted = layer(engine,"l7_intention")
        assert any(row["source_event_ids"] == [event.event_id] for row in extracted["items"])
        identifier = "add:"+hashlib.sha256(event.event_id.encode()).hexdigest()
        assert wait_task(engine,identifier)["state"] in {"completed","partial"}
        count = len(extracted["items"])
        assert assembly.method.observe(event).processing_status == "completed"
        assert len(layer(engine,"l7_intention")["items"]) == count
    finally:
        assembly.method.close()
    reopened = open_backend(tmp_path,create=False)
    try:
        assert reopened.method.engine.sdk_call("semantic_task", task_id="evolve-real")["state"] == "completed"
        assert set(ids) <= {row["item_id"] for row in layer(reopened.method.engine,"l6_schema")["items"]}
    finally:
        reopened.method.close()

    # 保留原账本，仅移动此合成库文件模拟缺失；不能默默重建空任务历史。
    ledger = tmp_path/"engine/semantic.sqlite3"
    ledger.rename(ledger.with_suffix(".saved"))
    with pytest.raises(ValueError,match="incomplete"):
        open_backend(tmp_path,create=False)


@pytest.mark.parametrize("scenario", ["slow", "blocked_write_loop"])
def test_native_background_does_not_hold_foreground_rpc_and_correction_isolates_old_derivatives(tmp_path,scenario):
    assembly = open_backend(tmp_path,scenario=scenario)
    engine = assembly.method.engine
    try:
        engine.sdk_call("semantic_enqueue", task_id="slow")
        # 原生首次加载聚类依赖的冷启动不属于前台召回RT；等到模型延迟窗口
        # 已实际开始才计时，不能拿排队/启动时间冒充并发证据。
        until = monotonic()+60
        while not (tmp_path/"engine/ab-delay-active").exists() and monotonic()<until:
            sleep(0.02)
        assert (tmp_path/"engine/ab-delay-active").exists()
        started = perf_counter()
        support = engine.recall("检查资料")
        elapsed = perf_counter()-started
        assert support.retrieved and "模型归纳" not in support.context
        assert "合成小明" in support.context
        assert any("ab-old-source" in (row.source_event_ids or ()) for row in support.retrieved)
        assert elapsed < 1.5, elapsed
        background = wait_task(engine,"slow")
        assert background["state"] == "completed"
        (tmp_path/"ab-latency.json").write_text(json.dumps({"foreground_recall_ms":elapsed*1000,
            "background_task_ms":background["elapsed_ms"],"injected_model_delay_ms":2000,
            "scope":"fixed_sdk_synthetic_model_cpu_no_audio", "scenario":scenario},indent=2),encoding="utf-8")
        engine.sdk_call("update", memory_id="ab-fact-0", content="合成纠正：无需反复核查")
        assert engine.sdk_call("get",memory_id="ab-fact-0")["content"].endswith("无需反复核查")
        assert engine.sdk_call("semantic_status")["schema_state"] == "isolated"
        assert layer(engine,"l6_schema",state="active")["items"] == []
        assert layer(engine,"l7_intention",state="active")["items"] == []
        assert "模型归纳" not in engine.recall("检查资料").context
        engine.sdk_call("delete",memory_id="ab-fact-1")
        assert engine.sdk_call("get",memory_id="ab-fact-1") is None
        assert engine.sdk_call("get",memory_id="ab-fact-2") is not None
        engine.configure_background_writes(write_enabled=False)
        assert engine.sdk_call("semantic_status")["paused"] is True
        from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
        with pytest.raises(HyResponseError):
            engine.sdk_call("semantic_enqueue",task_id="paused-task")
        assert layer(engine,"l7_intention")["items"]
        engine.configure_background_writes(write_enabled=True)
    finally:
        assembly.method.close()


def test_real_runtime_management_readback_then_rederive_preserves_correction_sources(tmp_path):
    from longmemory.application.memory_runtime import MemoryRuntime
    assembly = open_backend(tmp_path)
    runtime = MemoryRuntime(tmp_path/"sources.db",method=assembly.method,backend_assembly=assembly)
    engine = assembly.method.engine
    try:
        engine.sdk_call("semantic_enqueue",task_id="initial")
        assert wait_task(engine,"initial")["state"] == "completed"
        item = assembly.management.get_item("ab-fact-0")
        identifier = str(uuid4())
        content = "合成用户已纠正核查偏好"
        source = MemoryEvent("hy-management:"+identifier,"user",content,datetime.now(UTC),"ab-management")
        result = runtime.administer_extension("hy_memory","correct",item_id=item.item_id,request_id=identifier,
            expected_revision=item.revision,source=source,content=content)
        assert result["state"] == "completed"
        assert runtime.source_detail(source.event_id)["content"] == content
        assert wait_task(engine,result["derivation_task_id"])["state"] == "completed"
        traces = engine.recall("检查资料").retrieved
        assert any("模型归纳" in row.content and source.event_id in row.source_event_ids for row in traces)
        item = assembly.management.get_item("ab-fact-1")
        identifier = str(uuid4())
        source = MemoryEvent("hy-management:"+identifier,"user","删除这条记忆："+item.item_id,datetime.now(UTC),"ab-management")
        result = runtime.administer_extension("hy_memory","delete",item_id=item.item_id,request_id=identifier,
            expected_revision=item.revision,source=source)
        assert result["state"] == "completed"
        assert wait_task(engine,result["derivation_task_id"])["state"] == "completed"
        assert engine.sdk_call("get",memory_id=item.item_id) is None
        assert "模型归纳" not in engine.recall("检查资料").context
    finally:
        runtime.close()


def test_real_sdk_owner_termination_preserves_uncertain_task_without_automatic_replay(tmp_path):
    assembly = open_backend(tmp_path,scenario="slow")
    engine = assembly.method.engine
    try:
        engine.sdk_call("semantic_enqueue",task_id="terminated-owner")
        until = monotonic()+20
        while not (tmp_path/"engine/ab-delay-active").exists() and monotonic()<until:
            sleep(0.02)
        assert (tmp_path/"engine/ab-delay-active").exists()
        # 仅终止此测试创建的子进程；不按名称/端口扫描或结束其它进程。
        engine._client.client._stop()
    finally:
        assembly.method.close()
    reopened = open_backend(tmp_path,create=False)
    try:
        engine = reopened.method.engine
        row = engine.sdk_call("semantic_task",task_id="terminated-owner")
        assert row["state"] == "uncertain" and row["reason_code"] == "owner_restart"
        assert engine.sdk_call("semantic_status")["schema_state"] == "isolated"
        assert engine.sdk_call("semantic_enqueue",task_id="terminated-owner")["state"] == "uncertain"
        assert engine.sdk_call("diagnostics")["simulated_model_requests"] == 0
    finally:
        reopened.method.close()


def test_candidate_snapshot_is_native_readonly_and_invalidates_for_background_and_restart(tmp_path):
    assembly = open_backend(tmp_path,scenario="slow")
    engine = assembly.method.engine
    vector = [1.0]+[0.0]*7
    try:
        before = engine.sdk_call("diagnostics")
        intentions = layer(engine,"l7_intention")["items"]
        source_digest = hashlib.sha256((tmp_path/"sources.db").read_bytes()).hexdigest()
        snapshot = engine.candidate_snapshot(query_embedding=vector)
        assert snapshot["read_status"] == "readable"
        assert snapshot["policy"] == "latest_only_no_history_expansion_no_models_no_semantic_writes"
        assert any("未来意图" in row["content"] for row in snapshot["items"])
        assert all("expired" not in row["content"] for row in snapshot["items"])
        assert engine.candidate_validate(snapshot_token=snapshot["snapshot_token"],memory_digest=snapshot["memory_digest"])["valid"]
        assert not engine.candidate_validate(snapshot_token=snapshot["snapshot_token"],memory_digest="bad")["valid"]
        assert layer(engine,"l7_intention")["items"] == intentions
        assert hashlib.sha256((tmp_path/"sources.db").read_bytes()).hexdigest() == source_digest
        assert engine.sdk_call("diagnostics")["simulated_model_requests"] == before["simulated_model_requests"]
        assert engine.sdk_call("semantic_status")["task_counts"] == {}
        engine.sdk_call("semantic_enqueue",task_id="after-candidate")
        until = monotonic()+20
        while not (tmp_path/"engine/ab-delay-active").exists() and monotonic()<until:
            sleep(0.02)
        assert engine.candidate_snapshot(query_embedding=vector)["read_status"] == "busy"
        assert not engine.candidate_validate(snapshot_token=snapshot["snapshot_token"])["valid"]
        assert wait_task(engine,"after-candidate")["state"] == "completed"
        fresh = engine.candidate_snapshot(query_embedding=vector)
        assert fresh["revision"] > snapshot["revision"]
        assert fresh["epoch"] == snapshot["epoch"]
        assert engine.candidate_validate(snapshot_token=fresh["snapshot_token"])["valid"]
    finally:
        assembly.method.close()
    reopened = open_backend(tmp_path,create=False)
    try:
        assert not reopened.method.engine.candidate_validate(snapshot_token=fresh["snapshot_token"])["valid"]
    finally:
        reopened.method.close()
