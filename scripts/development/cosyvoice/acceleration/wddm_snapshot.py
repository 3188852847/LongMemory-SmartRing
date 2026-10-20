"""WDDM共享桌面的项目模型窗口：只读取证，不推断C+G为纯图形，不停止进程。"""

# 采集器冻结自AD 172a355，原文件SHA256 87ec064da57cded02bd3881724ba03fc0b29b5b62d3613c3f9e96001ff2f8892。
# AG准入层另加收据/精确集合/外层Job成员校验，不跨工作树导入AD模块。

import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import io
import json
import ntpath
import os
import subprocess
import xml.etree.ElementTree as ET


class GPUWindowBlocked(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("project_model_window_blocked:" + ",".join(
            f"{row.get('pid', '?')}:{row['reason']}" for row in report["blockers"]))


def _decode(raw):
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # nvidia-smi在本机输出ACP936字节但XML声明UTF-8，不能替换乱码后比路径。
        return raw.decode("mbcs")


def image_identity(pid):
    """PROCESS_QUERY_LIMITED_INFORMATION；不申请写权限，不提升权限。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    result = {"pid": pid, "creation_token": None, "executable_path": None}
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return {**result, "image_access_error": ctypes.get_last_error()}
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times]):
            result["creation_token"] = "filetime:" + str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        count = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(count.value)
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(count)):
            result["executable_path"] = buffer.value
        else:
            result["image_access_error"] = ctypes.get_last_error()
        return result
    finally:
        kernel.CloseHandle(handle)


def parse_nvml(xml_text, compute_text):
    root = ET.fromstring(xml_text)
    gpus = root.findall("gpu")
    if len(gpus) != 1:
        raise ValueError("one_target_gpu_required")
    gpu = gpus[0]
    processes = {}
    for item in gpu.findall("./processes/process_info"):
        pid = int(item.findtext("pid"))
        processes[pid] = {"pid": pid, "context_type": item.findtext("type", "unknown").strip(),
                          "nvml_path": item.findtext("process_name") or None}
    for row in csv.reader(io.StringIO(compute_text)):
        if row:
            pid = int(row[0].strip())
            processes.setdefault(pid, {"pid": pid, "context_type": "unknown", "nvml_path": None})
    return {"gpu_uuid": gpu.findtext("uuid"), "driver_model": gpu.findtext("./driver_model/current_dm"),
            "driver_version": root.findtext("driver_version"), "processes": list(processes.values())}


def collect_snapshot(run=subprocess.run):
    raw = run(["nvidia-smi", "-q", "-x", "-i", "0"], capture_output=True, timeout=10, check=True).stdout
    # XML定位UUID，CSV只补PID并保留缺失上下文类型；不相信CSV名称或显存N/A能分类。
    initial = parse_nvml(_decode(raw), "")
    csv_raw = run(["nvidia-smi", "--id=" + initial["gpu_uuid"], "--query-compute-apps=pid,process_name",
                   "--format=csv,noheader,nounits"], capture_output=True, timeout=10, check=True).stdout
    result = parse_nvml(_decode(raw), _decode(csv_raw))
    if not result["processes"]:
        result.update(captured_at_utc=datetime.now(timezone.utc).isoformat(),
                      evidence="NVML_nvidia_smi_XML_plus_CSV_no_processes", physical_gpu_exclusive=False)
        return result
    ids = ",".join(str(row["pid"]) for row in result["processes"])
    script = r'''[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$ids=@(IDS); $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
$targets=@($all | Where-Object { $_.ProcessId -in $ids })
$wanted=@($ids)+@($targets | ForEach-Object { $_.ParentProcessId })
@($all | Where-Object { $_.ProcessId -in $wanted } | ForEach-Object {
 [pscustomobject]@{pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;name=$_.Name;
 session_id=[int]$_.SessionId;creation_utc=$_.CreationDate.ToUniversalTime().ToString('o');path=$_.ExecutablePath}
}) | ConvertTo-Json -Depth 4 -Compress
'''.replace("IDS", ids)
    cim_raw = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                  capture_output=True, timeout=20, check=True).stdout
    cim = json.loads(cim_raw.decode("utf-8-sig") if isinstance(cim_raw, bytes) else cim_raw)
    by_pid = {row["pid"]: row for row in (cim if isinstance(cim, list) else [cim])}
    for process in result["processes"]:
        meta = by_pid.get(process["pid"], {})
        process.update(image_identity(process["pid"]))
        process.update(name=meta.get("name"), parent_pid=meta.get("parent_pid"), session_id=meta.get("session_id"))
        if process["creation_token"] is None and meta.get("creation_utc"):
            process["creation_token"] = "cim:" + meta["creation_utc"]
        if process["executable_path"] is None and meta.get("path"):
            process["executable_path"] = meta["path"]
        process["identity_state"] = "verified_image" if process["executable_path"] and process["creation_token"] else "unresolved"
        parent = by_pid.get(process.get("parent_pid"), {})
        process["parent_identity"] = {key: parent.get(key) for key in ("pid", "name", "creation_utc", "session_id")}
        # 仅标出可交主会话审查的受保护OS角色，绝不在这里批准；无图像路径的其他程序仍未解析。
        kernel_role = process["pid"] == 4 and process["name"] == "System" and process["parent_pid"] == 0 and process["session_id"] == 0
        dwm_role = (process["name"] == "dwm.exe" and parent.get("name") == "winlogon.exe"
                    and parent.get("session_id") == process["session_id"] and parent.get("creation_utc"))
        if (process["identity_state"] == "unresolved" and process["creation_token"]
                and process.get("image_access_error") == 5 and (kernel_role or dwm_role)):
            process["identity_state"] = "protected_os_logical"
    result.update(captured_at_utc=datetime.now(timezone.utc).isoformat(),
                  evidence="NVML_nvidia_smi_XML_plus_CSV_Win32_image_times_CIM",
                  physical_gpu_exclusive=False)
    return result


def _path(value):
    return ntpath.normcase(value) if isinstance(value, str) else None


def same_image(actual, expected):
    return (actual.get("pid") == expected.get("pid") and bool(actual.get("creation_token"))
            and actual["creation_token"] == expected.get("creation_token")
            and bool(actual.get("executable_path"))
            and _path(actual["executable_path"]) == _path(expected.get("executable_path")))


def classify(snapshot, baseline, own_identity=None):
    blockers, approved = [], []
    if (snapshot.get("driver_model") != "WDDM" or snapshot.get("gpu_uuid") != baseline.get("gpu_uuid")
            or baseline.get("reviewed_by") != "main_session" or not baseline.get("reviewed_at_utc")):
        blockers.append({"reason": "reviewed_matching_wddm_desktop_baseline_required"})
    entries = baseline.get("processes", [])
    indexed = {entry.get("pid"): entry for entry in entries}
    if len(indexed) != len(entries):
        blockers.append({"reason": "duplicate_background_pid"})
    for process in snapshot["processes"]:
        pid, kind = process["pid"], process["context_type"]
        if own_identity is not None and same_image(process, own_identity):
            approved.append({"pid": pid, "classification": "owned_benchmark_model"})
            continue
        entry = indexed.get(pid)
        reason = None
        if kind not in {"G", "C+G"}:
            reason = "compute_or_unknown_context_not_background"
        elif entry is None or entry.get("background_only") is not True:
            reason = "unapproved_background_identity"
        elif kind != entry.get("context_type"):
            reason = "background_context_changed"
        elif process["identity_state"] == "verified_image":
            if entry.get("approval_kind") != "image_identity" or not same_image(process, entry):
                reason = "background_image_or_creation_changed"
        elif process["identity_state"] == "protected_os_logical":
            keys = ("pid", "name", "creation_token", "parent_pid", "session_id", "parent_identity")
            if (entry.get("approval_kind") != "protected_os_identity"
                    or not entry.get("review_note") or any(process.get(key) != entry.get(key) for key in keys)):
                reason = "protected_os_identity_requires_explicit_exact_review"
        else:
            reason = "unresolved_owner_identity"
        if reason:
            blockers.append({"pid": pid, "reason": reason, "context_type": kind,
                             "identity_state": process.get("identity_state")})
        else:
            approved.append({"pid": pid, "classification": "reviewed_shared_desktop_context", "context_type": kind})
    return {"scope": "project_model_window_shared_windows_desktop", "physical_gpu_exclusive": False,
            "allowed": not blockers, "blockers": blockers, "approved": approved,
            "snapshot": snapshot, "background_noise_present": True,
            "same_process_background_workload_not_observable": True}


def ensure_window(receipt, *, own_identity=None):
    report = classify(collect_snapshot(), receipt.get("shared_desktop_baseline", {}), own_identity)
    if not report["allowed"]:
        raise GPUWindowBlocked(report)
    return report
