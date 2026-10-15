"""只在隔离合成目录验证元数据预算；没有删除或读取正文。"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from longmemory.infrastructure.logging.retention import retention_plan


def stream(root, name, size=10, age=10):
    path = root / "data/logs/diagnostics" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (2_000_000 - age * 86400,) * 2)
    return path


def test_budget_protects_active_unknown_recent_and_vendor_without_body_read(tmp_path, monkeypatch):
    active = stream(tmp_path, "api-1-" + "a" * 16 + ".jsonl")
    inactive = stream(tmp_path, "api-2-" + "b" * 16 + ".jsonl")
    stream(tmp_path, inactive.name + ".1", 20)
    recent = stream(tmp_path, "api-3-" + "c" * 16 + ".jsonl", age=1)
    unknown = stream(tmp_path, "api-4-" + "d" * 16 + ".jsonl")
    vendor = tmp_path / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/tmp/server.log"
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"synthetic-private" * 10)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("log body opened"))
    result = retention_plan(tmp_path, active_stream=active, inactive_streams=[active.name, inactive.name, recent.name],
                            budget_bytes=0, now=2_000_000)
    rows = {row["id"]: row for row in result["files"]}
    assert rows[active.name]["protection"] == "active_writer"
    assert rows[unknown.name]["protection"] == "unknown_writer"
    assert rows[recent.name]["protection"] == "minimum_age"
    assert result["candidate_streams"] == [inactive.name]
    assert result["candidate_bytes"] == 30 and result["unresolved_bytes"] == 30
    assert result["vendor_bytes"] == vendor.stat().st_size
    assert result["total_bytes"] == 60 + vendor.stat().st_size
    assert result["deletion_available"] is False
    assert str(tmp_path) not in json.dumps(result) and "private" not in json.dumps(result)
    assert inactive.exists() and vendor.exists()


def test_no_inactive_declaration_means_no_candidate_even_with_zero_budget(tmp_path):
    path = stream(tmp_path, "api-9-" + "a" * 16 + ".jsonl")
    result = retention_plan(tmp_path, budget_bytes=0, now=2_000_000)
    assert result["candidate_streams"] == [] and result["unresolved_bytes"] == path.stat().st_size


def test_unconfigured_root_is_not_reported_as_a_complete_zero_measurement():
    result = retention_plan(None)
    assert result["state"] == "unconfigured" and not result["complete"]
    assert result["candidate_streams"] == []


def test_link_or_windows_junction_never_scans_target(tmp_path, monkeypatch):
    outside = tmp_path / "synthetic-outside"
    outside.mkdir()
    (outside / "api-1-aaaaaaaaaaaaaaaa.jsonl").write_text("private")
    root = tmp_path / "root"
    link = root / "data/logs/diagnostics"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        assert result.returncode == 0
    try:
        monkeypatch.setattr(os, "scandir", lambda *a, **k: pytest.fail("linked directory scanned"))
        result = retention_plan(root, budget_bytes=0)
        assert result["state"] == "protected_link" and not result["complete"]
        assert result["candidate_streams"] == [] and result["total_bytes"] == 0
    finally:
        # 只移除本测试刚创建的链接本身，目标合成目录由 pytest 生命周期管理。
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_unknown_names_and_subdirectories_are_not_recursed_or_exposed(tmp_path):
    directory = tmp_path / "data/logs/diagnostics"
    directory.mkdir(parents=True)
    (directory / "private-filename.txt").write_text("synthetic")
    (directory / "folder").mkdir()
    (directory / "folder/nested.jsonl").write_text("synthetic")
    result = retention_plan(tmp_path, budget_bytes=0)
    assert result["total_bytes"] == 9
    assert "private-filename" not in json.dumps(result)
    assert result["candidate_streams"] == [] and not result["complete"]


def test_scan_bound_blocks_partial_plan(tmp_path, monkeypatch):
    import longmemory.infrastructure.logging.retention as module
    for number in range(3):
        stream(tmp_path, f"api-{number+1}-aaaaaaaaaaaaaaaa.jsonl")
    monkeypatch.setattr(module, "MAX_ENTRIES", 2)
    result = retention_plan(tmp_path, budget_bytes=0)
    assert result["state"] == "scan_limit_reached" and not result["complete"]
    assert result["candidate_streams"] == []


@pytest.mark.parametrize("name", ["../escape", "api-1-aaaaaaaaaaaaaaaa.jsonl.1", "anything", "C:/private"])
def test_inactive_stream_accepts_only_exact_process_stream_names(tmp_path, name):
    with pytest.raises(ValueError):
        retention_plan(tmp_path, inactive_streams=[name])
