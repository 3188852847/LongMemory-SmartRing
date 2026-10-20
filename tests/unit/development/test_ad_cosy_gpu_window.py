"""WDDM项目模型窗口的身份/上下文门；合成进程，不停止或启动GPU工作。"""

import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("ad_gpu_window_test", ROOT / "scripts/development/cosyvoice/gpu_window.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def process(pid=100, kind="C+G", path="C:/Apps/desktop.exe"):
    return {"pid": pid, "context_type": kind, "name": "desktop.exe", "creation_token": "filetime:10001",
            "executable_path": path, "identity_state": "verified_image", "parent_pid": 99,
            "session_id": 2, "parent_identity": {"pid": 99, "name": "launcher.exe", "creation_utc": "t0", "session_id": 2}}


def snapshot(*rows):
    return {"gpu_uuid": "gpu-fixture", "driver_model": "WDDM", "processes": list(rows)}


def baseline(*rows):
    return {"gpu_uuid": "gpu-fixture", "reviewed_by": "main_session", "reviewed_at_utc": "fixture-only",
            "processes": [{**row, "approval_kind": "image_identity", "background_only": True} for row in rows]}


def test_c_plus_g_is_only_reviewed_shared_context_never_relabelled_graphics_or_exclusive():
    row = process()
    result = gate.classify(snapshot(row), baseline(row))
    assert result["allowed"] and result["physical_gpu_exclusive"] is False
    assert result["background_noise_present"]
    assert result["approved"] == [{"pid": 100, "classification": "reviewed_shared_desktop_context", "context_type": "C+G"}]
    assert not gate.classify(snapshot(row), baseline())["allowed"]


@pytest.mark.parametrize("change", [{"creation_token": "filetime:20002"},
    {"executable_path": "C:/Apps/another.exe"}, {"pid": 101}, {"context_type": "C"},
    {"context_type": "unknown"}, {"creation_token": None},
    {"identity_state": "unresolved", "executable_path": None}])
def test_changed_new_reused_or_unresolved_owner_is_rejected(change):
    original = process()
    assert not gate.classify(snapshot({**original, **change}), baseline(original))["allowed"]


def test_pure_compute_is_rejected_even_if_someone_puts_it_in_desktop_baseline():
    row = process(kind="C", path="D:/Models/python.exe")
    result = gate.classify(snapshot(row), baseline(row))
    assert not result["allowed"]
    assert result["blockers"][0]["reason"] == "compute_or_unknown_context_not_background"


def test_only_exact_current_benchmark_model_identity_is_accepted_as_owned_compute():
    row = process(kind="C", path="D:/Python/python.exe")
    assert gate.classify(snapshot(row), baseline(), own_identity=row)["allowed"]
    assert not gate.classify(snapshot(row), baseline(), own_identity={**row, "creation_token": "reused"})["allowed"]


def test_protected_os_logical_role_requires_separate_explicit_review_and_exact_parent():
    row = {**process(path=None), "identity_state": "protected_os_logical", "name": "dwm.exe"}
    saved = baseline(row)
    assert not gate.classify(snapshot(row), saved)["allowed"]
    saved["processes"][0].update(approval_kind="protected_os_identity", review_note="main inspected protected OS role")
    assert gate.classify(snapshot(row), saved)["allowed"]
    changed = copy.deepcopy(row)
    changed["parent_identity"]["creation_utc"] = "reused-parent"
    assert not gate.classify(snapshot(changed), saved)["allowed"]


@pytest.mark.parametrize("changes", [{"gpu_uuid": "another-gpu"}, {"reviewed_by": "auto-script"},
                                    {"reviewed_at_utc": None}])
def test_baseline_capture_does_not_authorize_itself_or_another_gpu(changes):
    row = process()
    assert not gate.classify(snapshot(row), {**baseline(row), **changes})["allowed"]


def test_duplicate_background_ids_and_non_wddm_are_not_silently_accepted():
    row = process()
    assert not gate.classify(snapshot(row), baseline(row, row))["allowed"]
    assert not gate.classify({**snapshot(row), "driver_model": "TCC"}, baseline(row))["allowed"]


def test_compute_csv_adds_missing_pid_as_unknown_and_cannot_overwrite_xml_type():
    xml = '''<nvidia_smi_log><driver_version>fixture</driver_version><gpu><uuid>gpu-fixture</uuid>
    <driver_model><current_dm>WDDM</current_dm></driver_model><processes>
    <process_info><pid>100</pid><type>C+G</type><process_name>C:/Apps/desktop.exe</process_name></process_info>
    <process_info><pid>200</pid><type>C</type><process_name>D:/Python/python.exe</process_name></process_info>
    </processes></gpu></nvidia_smi_log>'''
    result = gate.parse_nvml(xml, "100, C:/Apps/desktop.exe\n200, D:/Python/python.exe\n300, [Insufficient Permissions]\n")
    assert {row["pid"]: row["context_type"] for row in result["processes"]} == {100: "C+G", 200: "C", 300: "unknown"}


def test_cim_protected_roles_do_not_turn_unresolved_third_party_program_into_os_identity(monkeypatch):
    xml = '<nvidia_smi_log><gpu><uuid>gpu-fixture</uuid><driver_model><current_dm>WDDM</current_dm></driver_model><processes>'
    for pid in (4, 200, 300):
        xml += f'<process_info><pid>{pid}</pid><type>C+G</type><process_name /></process_info>'
    xml += '</processes></gpu></nvidia_smi_log>'
    cim = [{"pid": 4, "name": "System", "parent_pid": 0, "session_id": 0, "creation_utc": "boot", "path": None},
           {"pid": 200, "name": "dwm.exe", "parent_pid": 201, "session_id": 2, "creation_utc": "later", "path": None},
           {"pid": 201, "name": "winlogon.exe", "parent_pid": 0, "session_id": 2, "creation_utc": "earlier", "path": None},
           {"pid": 300, "name": "Main.exe", "parent_pid": 301, "session_id": 2, "creation_utc": "later", "path": None}]
    def run(command, **_kwargs):
        if "-x" in command:
            return SimpleNamespace(stdout=xml.encode())
        if command[0] == "nvidia-smi":
            return SimpleNamespace(stdout=b"4, [Insufficient Permissions]\n200, [Insufficient Permissions]\n300, [Insufficient Permissions]")
        return SimpleNamespace(stdout=json.dumps(cim).encode())
    monkeypatch.setattr(gate, "image_identity", lambda pid: {"pid": pid, "creation_token": None,
                        "executable_path": None, "image_access_error": 5})
    result = gate.collect_snapshot(run)
    assert {row["pid"]: row["identity_state"] for row in result["processes"]} == {
        4: "protected_os_logical", 200: "protected_os_logical", 300: "unresolved"}


@pytest.mark.skipif(os.name != "nt", reason="Windows readonly identity API")
def test_actual_current_cpu_process_has_image_and_non_reusable_creation_token():
    actual = gate.image_identity(os.getpid())
    assert actual["pid"] == os.getpid()
    assert actual["creation_token"].startswith("filetime:")
    assert Path(actual["executable_path"]).is_file()
