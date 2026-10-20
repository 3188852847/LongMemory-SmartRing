"""AB: 固定真实SDK的图式归纳/意图读取/管理失效与重开，不代表模型质量。"""

from pathlib import Path
from datetime import UTC, datetime
import hashlib
import json
import os
import sqlite3
from contextlib import closing
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


def open_backend(root, *, create=True, scenario="normal", semantic=True):
    from dataclasses import replace
    prototype = replace(SETTINGS,semantic_layers_enabled=semantic)
    script = ("import sys;sys.path.insert(0,"+repr(str(ROOT/"src"))+");sys.path.insert(0,"+repr(str(ROOT/"tests/fixtures"))+");"
        "from hy_semantic_worker import run;run("+repr(scenario)+")")
    def factory(workspace, *, create):
        from dataclasses import replace
        settings = replace(prototype, management_writes_enabled=True, management_exclusive_profile=True)
        return HyProcessClient(python=SDK, workspace=workspace, settings=settings, create=create,
            command=[str(SDK), "-I", "-X", "utf8", "-B", "-c", script])
    proof = {"protocol":2,"sdk_version":"2.0.3",
        "rpc_source_sha256":management_primitives_identity(), "real_sdk_rpc_verified":True,
        "semantic_background_writes":"managed_v1", "derivation_invalidation_verified":True,"read_only_intention_verified":True} if semantic else {
            "sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),
            "real_sdk_rpc_verified":True,"semantic_background_writes_disabled":True}
    return assemble_hy_backend(settings=prototype, state_directory=root/"engine", source_path=root/"sources.db",
        create=create, client_factory=factory, management_verification=proof)


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


def test_real_unverified_profile_intention_formal_candidate_labels_and_batch_capture_diagnostics(tmp_path):
    assembly=open_backend(tmp_path,scenario="projection")
    engine=assembly.method.engine
    try:
        formal=engine.recall("检查资料")
        profile=next(row for row in formal.retrieved if row.item_id=="ab-profile")
        intention=next(row for row in formal.retrieved if row.item_id=="ab-intention-live")
        assert "当前画像由模型提取／聚合；语义来源尚未证实完整" in profile.content
        assert "未来意图由模型提取；语义来源尚未证实完整" in intention.content
        snapshot=engine.candidate_snapshot(query_embedding=[1.0]+[0.0]*7,limit=10)
        for channel in ("profile","proactive"):
            assert all("语义来源尚未证实完整" in row["content"] for row in snapshot["items"] if row["channel"]==channel)
        assert layer(engine,"l0_basic_info")["items"][0]["provenance"]["semantic_source_complete"] is False
        assert all(row["provenance"]["semantic_source_complete"] is False for row in layer(engine,"l7_intention")["items"])
        event=MemoryEvent("ab-batch-capture","user","独立合成输入。",datetime.now(UTC),"ab-batch")
        assert assembly.method.observe(event).processing_status=="completed"
        capture=engine.sdk_call("diagnostics")["provenance_capture"]
        assert capture["node_count"]==11 and capture["node_limit"]==10000
        assert capture["ledger_connections"]==1 and capture["audit_connections"]==0
        assert all(capture[key]>=0 for key in ("list_ms","ledger_ms","projection_ms","elapsed_ms"))
        wait_task(engine,"add:"+hashlib.sha256(event.event_id.encode()).hexdigest())
    finally:
        assembly.method.close()


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


@pytest.mark.parametrize("semantic",[False,True])
def test_real_nonempty_profile_candidate_matches_formal_prepare_content_and_sources(tmp_path,semantic):
    from longmemory.bootstrap import build_backend_runtime
    assembly = open_backend(tmp_path,scenario="projection",semantic=semantic)
    runtime = build_backend_runtime(assembly)
    engine = assembly.method.engine
    try:
        snapshot = engine.candidate_snapshot(query_embedding=[1.0]+[0.0]*7)
        assert snapshot["read_status"] == "readable"
        profile = next(row for row in snapshot["items"] if row["channel"]=="profile")
        assert "合成小明" in profile["content"] and profile["source_event_ids"] == ["ab-profile-source"]
        native = engine._client.candidate_snapshot(query_embedding=[1.0]+[0.0]*7)
        assert native["memory_digest"] == snapshot["memory_digest"]
        turn,_ = runtime.prepare_round_screen("检查资料",client_round_id="e"*32,session_id="f"*32)
        actual = [(row.item_id,row.content,list(row.source_event_ids) if row.source_event_ids else None)
            for row in turn.support.retrieved]
        expected = [(row["memory_id"],row["content"],row["source_event_ids"]) for row in snapshot["items"]]
        assert actual == expected
        assert turn.support.context == "\n".join(row["content"] for row in snapshot["items"])
        assert engine.candidate_validate(snapshot_token=snapshot["snapshot_token"],memory_digest=snapshot["memory_digest"])["valid"]
        runtime.cancel_round_screen(turn.event.event_id,reason="cancelled",client_round_id="e"*32)
    finally:
        runtime.close()


def _source_binding(root):
    with closing(sqlite3.connect((root/"sources.db").as_uri()+"?mode=ro",uri=True)) as db:
        return db.execute("SELECT engine_name FROM source_journal_identity").fetchone()[0]


def _task_rows(root):
    with closing(sqlite3.connect((root/"engine/semantic.sqlite3").as_uri()+"?mode=ro",uri=True)) as db:
        return db.execute("SELECT id,kind,payload,state,created,finished,elapsed_ms,reason FROM tasks ORDER BY id").fetchall()


def test_real_pro_source_enable_semantic_reopen_rollback_preserves_source_graph_and_tasks(tmp_path):
    old = MemoryEvent("ab-old-pro-source","user","合成旧pro来源",datetime(2026,10,19,tzinfo=UTC),"ab-old-pro")
    new = MemoryEvent("ab-new-semantic-source","user","合成语义计划来源",datetime(2026,10,20,tzinfo=UTC),"ab-new-semantic")
    rollback = MemoryEvent("ab-pro-after-rollback","user","合成回退pro后的新增来源",datetime(2026,10,21,tzinfo=UTC),"ab-rollback")
    assembly = open_backend(tmp_path,scenario="projection",semantic=False)
    try:
        assert assembly.method.implementation_version == "sdk-2.0.3-adapter-1"
        assert assembly.method.observe(old).processing_status == "completed"
        binding = _source_binding(tmp_path)
        assert json.loads(binding)["version"] == "sdk-2.0.3-adapter-1"
    finally:
        assembly.method.close()
    original_bytes = (tmp_path/"sources.db").read_bytes()
    from dataclasses import replace
    with pytest.raises(ValueError,match="verification"):
        assemble_hy_backend(settings=replace(SETTINGS,semantic_layers_enabled=True),state_directory=tmp_path/"engine",
            source_path=tmp_path/"sources.db",create=False,client_factory=lambda *a,**kw:pytest.fail("old proof must not start SDK"),
            management_verification={"sdk_version":"2.0.3","rpc_source_sha256":management_primitives_identity(),
                "real_sdk_rpc_verified":True,"semantic_background_writes_disabled":True})
    assert (tmp_path/"sources.db").read_bytes()==original_bytes
    assembly = open_backend(tmp_path,create=False,scenario="projection",semantic=True)
    try:
        assert assembly.method.implementation_version == "sdk-2.0.3-semantic-adapter-2"
        assert assembly.method.engine.source_storage_version == "sdk-2.0.3-adapter-1"
        assert _source_binding(tmp_path)==binding
        assert assembly.method.source_detail(old.event_id)["content"]==old.content
        before = assembly.method.engine.sdk_call("diagnostics")["simulated_model_requests"]
        assert assembly.method.observe(old).processing_status == "completed"
        assert assembly.method.engine.sdk_call("diagnostics")["simulated_model_requests"]==before
        assert assembly.method.observe(new).processing_status == "completed"
        task_id="add:"+hashlib.sha256(new.event_id.encode()).hexdigest()
        assert wait_task(assembly.method.engine,task_id)["state"]=="completed"
        graph_ids={row["item_id"] for row in layer(assembly.method.engine,"l6_schema")["items"]}
        assert graph_ids
        task_rows = _task_rows(tmp_path)
    finally:
        assembly.method.close()
    assembly = open_backend(tmp_path,create=False,scenario="projection",semantic=True)
    try:
        assert _source_binding(tmp_path)==binding and _task_rows(tmp_path)==task_rows
        assert {row["item_id"] for row in layer(assembly.method.engine,"l6_schema")["items"]}==graph_ids
        assert assembly.method.source_detail(new.event_id)["content"]==new.content
    finally:
        assembly.method.close()
    graph_digest=hashlib.sha256((tmp_path/"engine/sdk/graph").read_bytes()).hexdigest()
    assembly = open_backend(tmp_path,create=False,scenario="projection",semantic=False)
    try:
        assert _source_binding(tmp_path)==binding
        assert _task_rows(tmp_path)==task_rows
        assert assembly.method.source_detail(new.event_id)["state"]=="completed"
        assert assembly.method.observe(rollback).processing_status=="completed"
        assert _task_rows(tmp_path)==task_rows
    finally:
        assembly.method.close()
    assert hashlib.sha256((tmp_path/"engine/sdk/graph").read_bytes()).hexdigest()==graph_digest
    assembly = open_backend(tmp_path,create=False,scenario="projection",semantic=True)
    try:
        assert _source_binding(tmp_path)==binding
        assert _task_rows(tmp_path)==task_rows
        assert assembly.method.engine.sdk_call("semantic_status")["schema_state"]=="isolated"
        assert {row["item_id"] for row in layer(assembly.method.engine,"l6_schema")["items"]}==graph_ids
        assert "模型归纳" not in assembly.method.engine.recall("检查资料").context
        for event in (old,new,rollback):
            assert assembly.method.source_detail(event.event_id)["content"]==event.content
            assert assembly.method.source_detail(event.event_id)["state"]=="completed"
    finally:
        assembly.method.close()


def test_real_pre_fix_semantic_source_alias_reopens_without_identity_rewrite(tmp_path,monkeypatch):
    from longmemory.methods.hy_memory import assembly as module
    from longmemory.bootstrap import assemble_backend
    # 使用原公共装配真实创建旧semantic-adapter-2绑定，不通过SQL改写模拟旧库。
    def original_assembly(engine,resources,source,*,management,create):
        return assemble_backend(method=engine,resources=resources,source_path=source,management=management,create_sources=create)
    with monkeypatch.context() as patch:
        patch.setattr(module,"_assemble_hy_sources",original_assembly)
        old = open_backend(tmp_path,scenario="projection",semantic=True)
        try:
            event=MemoryEvent("ab-pre-fix-semantic-source","assistant","合成旧语义来源",datetime.now(UTC),"ab-alias")
            old.method.archive(event)
            binding=_source_binding(tmp_path)
            assert json.loads(binding)["version"]=="sdk-2.0.3-semantic-adapter-2"
        finally:
            old.method.close()
    for semantic in (True,False):
        current=open_backend(tmp_path,create=False,scenario="projection",semantic=semantic)
        try:
            assert _source_binding(tmp_path)==binding
            assert current.method.source_detail(event.event_id)["content"]==event.content
            assert current.method.engine.source_storage_version=="sdk-2.0.3-adapter-1"
        finally:
            current.method.close()
