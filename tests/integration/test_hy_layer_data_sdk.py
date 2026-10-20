"""固定真实SDK/Chroma＋模拟模型，所有库为新合成；不读取日用资源。"""

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.assembly import management_primitives_identity
from longmemory.methods.hy_memory.layer_data import LAYERS
from longmemory.methods.hy_memory.process_client import HyProcessClient
from longmemory.methods.hy_memory.settings import HySettings


SDK = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON", "missing-owner-sdk"))
pytestmark = pytest.mark.skipif(not SDK.is_file(), reason="explicit owner-installed fixed SDK required")
ROOT = Path(__file__).resolve().parents[2]
SETTINGS = HySettings(user_id="aa-layer-synthetic", agent_id="aa-layer-agent", model_mode="synthetic_transport",
                      management_writes_enabled=True, management_exclusive_profile=True)


def open_runtime(root, *, create=True, scenario="normal", profile=True):
    # 测试factory只能以新合成目录运行。生产装配不接受HTTP提供命令。
    script = ("import sys; sys.path.insert(0," + repr(str(ROOT / "src")) + "); sys.path.insert(0,"
              + repr(str(ROOT / "tests" / "fixtures")) + "); from hy_layer_data_worker import run; run(" + repr(scenario) + ")")
    def factory(workspace, *, create):
        settings = SETTINGS if profile else HySettings(user_id=SETTINGS.user_id, agent_id=SETTINGS.agent_id, model_mode="synthetic_transport")
        return HyProcessClient(python=SDK, workspace=workspace, settings=settings, create=create,
            command=[str(SDK), "-I", "-X", "utf8", "-B", "-c", script])
    return build_hy_memory_runtime(settings=SETTINGS, state_directory=root / "engine", source_path=root / "sources.db",
        create=create, client_factory=factory, management_verification=None if not profile else {
            "sdk_version": "2.0.3", "rpc_source_sha256": management_primitives_identity(),
            "real_sdk_rpc_verified": True, "semantic_background_writes_disabled": True})


def page(runtime, layer, *, limit=20, offset=0, state="all"):
    return runtime.administer_extension("hy_memory", "layer_page", layer=layer, limit=limit, offset=offset, state=state)


def detail(runtime, layer, item_id):
    return runtime.administer_extension("hy_memory", "layer_detail", layer=layer, item_id=item_id)


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.name.endswith(".owner")}


def test_real_sdk_all_layers_history_scoped_native_pages_details_no_writes_and_restart(tmp_path):
    runtime = open_runtime(tmp_path)
    try:
        diagnostics = runtime._method.engine.sdk_call("diagnostics")
        assert diagnostics["actual_sdk_version"] == "2.0.3" and diagnostics["simulated_model_requests"] == 0
        before = snapshot(tmp_path)
        pages = [page(runtime, layer) for layer in LAYERS]
        assert all(result["data_state"] == "present" and result["read_status"] == "readable" for result in pages)
        assert pages[0]["items"][0]["basic_info"] == {"name": "合成小明", "location": "乙城"}
        assert pages[0]["items"][0]["item_id"] == "profile"
        assert pages[0]["items"][0]["stored_version_count"] == 2
        aggregate = detail(runtime, LAYERS[0], "profile")
        assert aggregate["item"]["field_sources"]["name"]["native_id"] == "profile-old"
        assert aggregate["item"]["field_sources"]["location"]["native_id"] == "profile-new"
        assert len(aggregate["versions"]) == 2
        assert detail(runtime, LAYERS[0], "profile-old")["item"]["kind"] == "stored_record"
        raw = page(runtime, LAYERS[1])
        assert any("真正SDK RAW" in item["content"] for item in raw["items"])
        assert pages[4]["sdk_support"] == "historical" and pages[5]["sdk_support"] == "reserved"
        assert pages[6]["generation_state"] == pages[7]["generation_state"] == "disabled"
        first = page(runtime, LAYERS[2], limit=2)
        assert first["total"] is None and first["has_more"] is True
        seen, offset = [], 0
        while True:
            result = page(runtime, LAYERS[2], limit=2, offset=offset)
            seen.extend(result["items"])
            if not result["has_more"]:
                assert result["total"] == len(seen)
                break
            offset += 2
        assert len(seen) == len({item["item_id"] for item in seen})
        assert {item["status"] for item in seen} == {"active", "superseded", "negated", "conflicted", "shadow", "archived"}
        assert page(runtime, LAYERS[2], state="superseded")["total"] == 1
        assert page(runtime, LAYERS[2], offset=9999)["total"] is None
        for foreign in ("other-user", "other-agent", "other-source", "other-layer"):
            with pytest.raises(LookupError):
                detail(runtime, LAYERS[2], foreign)
        long = detail(runtime, LAYERS[2], "long-native")["item"]
        assert len(long["content"]) == 32768 and long["content_chars"] == 40000 and long["content_truncated"]
        assert "PRIVATE_OTHER" not in json.dumps(pages)
        after = runtime._method.engine.sdk_call("diagnostics")
        assert after["simulated_model_requests"] == diagnostics["simulated_model_requests"]
        assert after["external_http_attempts"] == after["local_gateway_requests"] == 0
        assert snapshot(tmp_path) == before
        ids_before = [item["item_id"] for item in seen]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path, create=False)
    try:
        assert page(reopened, LAYERS[0])["items"][0]["basic_info"]["location"] == "乙城"
        ids_after, offset = [], 0
        while True:
            result = page(reopened, LAYERS[2], limit=2, offset=offset)
            ids_after.extend(item["item_id"] for item in result["items"])
            if not result["has_more"]:
                break
            offset += 2
        assert ids_after == ids_before
    finally:
        reopened.close()


def test_real_sdk_mock_extraction_raw_and_fact_read_without_further_model_calls(tmp_path):
    runtime = open_runtime(tmp_path, scenario="unseeded")
    try:
        event = MemoryEvent("sdk-extraction-source", "user", "合成用户喜欢无糖乌龙茶", datetime(2026, 10, 21, tzinfo=UTC), "synthetic-session")
        assert runtime._method.observe(event).processing_status == "completed"
        diagnostics = runtime._method.engine.sdk_call("diagnostics")
        assert diagnostics["simulated_model_requests"] > 0
        before = snapshot(tmp_path)
        raw, facts = page(runtime, LAYERS[1]), page(runtime, LAYERS[2])
        assert any("合成用户喜欢无糖乌龙茶" in item["content"] for item in raw["items"])
        assert facts["total"] == 1 and facts["items"][0]["source_event_ids"] == [event.event_id]
        assert detail(runtime, LAYERS[2], facts["items"][0]["item_id"])["item"]["source_event_ids"] == [event.event_id]
        after = runtime._method.engine.sdk_call("diagnostics")
        assert after["simulated_model_requests"] == diagnostics["simulated_model_requests"]
        assert after["external_http_attempts"] == after["local_gateway_requests"] == 0
        assert snapshot(tmp_path) == before
    finally:
        runtime.close()


def test_real_sdk_profile_sources_follow_exact_sdk_merge_for_status_branch_null_and_empty(tmp_path):
    runtime = open_runtime(tmp_path, scenario="profile_variants")
    try:
        result = detail(runtime, LAYERS[0], "profile")["item"]
        # SDK合并函数读取所有版本并按时间覆盖；并不只采用active链头。
        assert result["basic_info"] == {"name": None, "location": "丙城", "occupation": "合成职业", "employer": ""}
        assert result["field_sources"]["name"]["native_id"] == "profile-null"
        assert result["field_sources"]["location"]["native_id"] == "profile-branch"
        assert result["field_sources"]["occupation"]["native_id"] == "profile-negated"
        assert "name is" not in result["content"] and "employer is" not in result["content"]
        assert runtime._method.engine.sdk_call("diagnostics")["simulated_model_requests"] == 0
    finally:
        runtime.close()


@pytest.mark.parametrize("scenario, reason", [("scope_bad", "profile_scope_unproven"), ("profile_limit", "profile_history_limit")])
def test_real_sdk_incomplete_or_foreign_l0_never_returns_false_aggregate(tmp_path, scenario, reason):
    runtime = open_runtime(tmp_path, scenario=scenario)
    try:
        result = page(runtime, LAYERS[0])
        assert result["read_status"] == "unavailable" and result["reason_code"] == reason
        assert result["total"] is result["has_more"] is None and result["data_state"] == "unknown"
        assert result["items"] == [] and "PRIVATE_FOREIGN" not in json.dumps(result)
        assert runtime._method.engine.sdk_call("diagnostics")["simulated_model_requests"] == 0
    finally:
        runtime.close()


def test_real_sdk_graph_disabled_existing_marker_is_partial_not_empty_and_untouched(tmp_path):
    runtime = open_runtime(tmp_path, scenario="graph_marker")
    try:
        marker = tmp_path / "engine/sdk/graph"
        before = marker.read_bytes()
        for layer in LAYERS[6:]:
            result = page(runtime, layer)
            assert result["read_status"] == "partial" and result["coverage"] == "vdb_only_graph_unopened"
            assert result["total"] is None and result["data_state"] == "present"
            missing = detail(runtime, layer, "no-such-record")
            assert missing["read_status"] == "unavailable" and missing["data_state"] == "unknown"
        assert marker.read_bytes() == before
        assert runtime._method.engine.sdk_call("diagnostics")["simulated_model_requests"] == 0
    finally:
        runtime.close()


def test_real_sdk_l0_without_trusted_scope_stamp_is_unavailable_not_zero(tmp_path):
    runtime = open_runtime(tmp_path, profile=False)
    try:
        result = page(runtime, LAYERS[0])
        assert result["reason_code"] == "profile_scope_unproven" and result["total"] is None
        assert result["items"] == [] and result["data_state"] == "unknown"
        assert page(runtime, LAYERS[1])["data_state"] == "present"
    finally:
        runtime.close()
