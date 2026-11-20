"""真实 SDK/Chroma/中文路径 + 本地 MockTransport；不证明真实模型质量。"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import os

import pytest

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from longmemory.methods.hy_memory.settings import HySettings


ROOT = Path(__file__).resolve().parents[2]
SDK_PYTHON = Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON",
    str(ROOT / "local/runtime/hy-memory/.venv/Scripts/python.exe"))).resolve()
if os.environ.get("LONGMEMORY_TEST_HY_PYTHON") and not SDK_PYTHON.is_file():
    raise pytest.UsageError("LONGMEMORY_TEST_HY_PYTHON must point to an owner-installed interpreter")
pytestmark = pytest.mark.skipif(not SDK_PYTHON.is_file(), reason="owner-installed isolated Hy environment missing")
EVENT = MemoryEvent("real-sdk-synthetic-1", "user", "合成用户喜欢无糖乌龙茶", datetime(2026,1,1,tzinfo=UTC), "synthetic-session")


def open_runtime(root, *, create, model_mode="synthetic_transport"):
    return build_hy_memory_runtime(settings=HySettings(user_id="synthetic-real-sdk",model_mode=model_mode),
        state_directory=root / "中文引擎", source_path=root / "来源.db", create=create, python=SDK_PYTHON)


def test_real_sdk_network_denied_failure_and_source_persistence(tmp_path):
    runtime = open_runtime(tmp_path, create=True, model_mode="disabled")
    try:
        result = runtime._method.observe(EVENT)
        assert result.processing_status == "source_only"
        assert runtime.source_status(EVENT.event_id)["state"] == "failed"
        assert runtime.administer("listing","list_items",state="active").total == 0
        assert runtime._method.engine.sdk_call("diagnostics")["external_http_attempts"] == 0
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path, create=False, model_mode="disabled")
    try:
        assert reopened.source_detail(EVENT.event_id)["session_id"] == "synthetic-session"
        status = reopened.source_status(EVENT.event_id)
        with pytest.raises(UnsupportedCapabilityError):
            reopened.retry_source(EVENT.event_id, expected_attempt_id=status["attempt_id"])
    finally:
        reopened.close()


def test_real_sdk_simulated_models_management_recall_and_restart(tmp_path):
    runtime = open_runtime(tmp_path, create=True)
    try:
        assert runtime._method.observe(EVENT).processing_status == "completed"
        runtime._method.observe(replace(EVENT,event_id="assistant-1",role="assistant",content="建议养兔子"))
        runtime._method.observe(EVENT)
        page = runtime.administer("listing","list_items",state="active")
        assert page.total == 1
        item = runtime.administer("detail","get_item",page.items[0].item_id)
        assert item.source_event_ids == (EVENT.event_id,)
        after_page = runtime.administer("listing","list_items",state="active",limit=1,offset=1)
        assert after_page.total == page.total and after_page.items == ()
        support = runtime._method.recall("合成用户喜欢什么茶")
        assert support.retrieved[0].source_event_ids == (EVENT.event_id,)
        assert support.retrieved[0].dense_score is None
        assert not runtime.status()["method_capabilities"]["frozen_evaluation"]
        assert runtime.source_detail("assistant-1")["role"] == "assistant"
        diagnostics = runtime._method.engine.sdk_call("diagnostics")
        assert diagnostics["external_http_attempts"] == 0 and diagnostics["simulated_model_requests"] > 0
        with pytest.raises(UnsupportedCapabilityError):
            runtime.administer("deletion","delete_item",item.item_id,expected_revision=item.revision)
        assert not (tmp_path / "中文引擎/sdk/graph").exists()  # pro/graph-off 不初始化 Kuzu 库。
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path, create=False)
    try:
        assert reopened._method.observe(EVENT).processing_status == "completed"
        assert reopened.administer("listing","list_items",state="active").total == 1
        assert reopened._method.recall("茶").retrieved[0].source_event_ids == (EVENT.event_id,)
    finally:
        reopened.close()


def test_real_sdk_commit_before_platform_receipt_is_uncertain(tmp_path,monkeypatch):
    runtime = open_runtime(tmp_path, create=True)
    def receipt_failure(*args,**kwargs):
        raise OSError("synthetic receipt interruption")
    monkeypatch.setattr(runtime._method.journal,"finish",receipt_failure)
    try:
        with pytest.raises(OSError):
            runtime._method.observe(EVENT)
        assert runtime.administer("listing","list_items",state="active").total == 1
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path, create=False)
    try:
        status = reopened.source_status(EVENT.event_id)
        assert status["state"] == "uncertain"
        assert reopened._method.observe(EVENT).warning_code == "engine_explicit_retry_required"
        with pytest.raises(UnsupportedCapabilityError):
            reopened.retry_source(EVENT.event_id,expected_attempt_id=status["attempt_id"])
        assert reopened.administer("listing","list_items",state="active").total == 1
    finally:
        reopened.close()
