"""AG执行收据与AD v2 WDDM精确桌面基线；只授予外部已批准的项目模型窗口。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess

from . import wddm_snapshot as wddm
from .job_accounting import read_job_snapshot

CLOSED_WINDOW_IDS = {"AD-GPU-20261021-01", "AG-FLOW-GPU-20261021-01"}
SCOPE = "ag-flow-project-model-window"
SECONDS = 1320


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def read_receipt(path: Path, expected_sha256: str):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") or path.is_symlink() or path.stat().st_size > 256*1024:
        raise ValueError("main_session_receipt_digest_required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("receipt_bytes_changed_or_revoked")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("receipt_object_required")
    return value


def _time(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp
    except (AttributeError, ValueError):
        raise ValueError("receipt_utc_time_required") from None


def _matching_path(value, expected):
    return isinstance(value, str) and bool(value) and Path(value).is_absolute() and Path(value).resolve() == expected.resolve()


def validate_receipt(receipt: dict, *, checkout: Path, output: Path, production: Path,
                     commit: str, bindings_sha256: str, now=None, remaining=SECONDS):
    now = now or datetime.now(timezone.utc)
    window = receipt.get("window_id")
    if isinstance(window, str) and window in CLOSED_WINDOW_IDS:
        raise ValueError("closed_window_cannot_be_reused")
    required = (type(receipt.get("schema_version")) is int and receipt["schema_version"] == 2
        and receipt.get("scope") == SCOPE and receipt.get("state") == "active"
        and receipt.get("issued_by") == "main_session" and isinstance(window, str) and re.fullmatch(r"AG-FLOW-GPU-[A-Za-z0-9-]{4,64}", window)
        and all(receipt.get(k) is True for k in ("project_model_window", "production_stopped", "other_gpu_model_workers_stopped"))
        and receipt.get("physical_gpu_exclusive") is False and "exclusive_gpu" not in receipt
        and receipt.get("candidate_commit") == commit and re.fullmatch(r"[0-9a-f]{40}", commit or "")
        and receipt.get("bindings_sha256") == bindings_sha256 and re.fullmatch(r"[0-9a-f]{64}", bindings_sha256 or "")
        and type(receipt.get("max_seconds")) is int and receipt["max_seconds"] == SECONDS
        and _matching_path(receipt.get("checkout"), checkout)
        and _matching_path(receipt.get("output"), output)
        and _matching_path(receipt.get("production_root"), production))
    if not required:
        raise ValueError("matching_main_session_v2_project_model_receipt_required")
    issued, expires = _time(receipt.get("issued_at_utc")), _time(receipt.get("expires_at_utc"))
    if issued > now or expires <= issued or (expires-issued).total_seconds() > 3600 or (expires-now).total_seconds() < remaining+10:
        raise ValueError("receipt_expired_future_or_insufficient_window")
    baseline = receipt.get("shared_desktop_baseline")
    if (not isinstance(baseline, dict) or baseline.get("reviewed_by") != "main_session" or not baseline.get("gpu_uuid")
            or baseline.get("driver_model") != "WDDM" or not baseline.get("driver_version")):
        raise ValueError("main_reviewed_wddm_baseline_required")
    reviewed = _time(baseline.get("reviewed_at_utc"))
    if reviewed > issued or reviewed > now or (issued-reviewed).total_seconds() > 120:
        raise ValueError("fresh_exact_desktop_review_required")
    if receipt.get("desktop_baseline_sha256") != digest(baseline):
        raise ValueError("desktop_baseline_digest_mismatch")
    entries = baseline.get("processes")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries) or len({row.get("pid") for row in entries}) != len(entries):
        raise ValueError("exact_unique_desktop_process_set_required")
    for entry in entries:
        if type(entry.get("pid")) is not int or not entry.get("creation_token") or entry.get("context_type") not in {"G", "C+G"} or entry.get("background_only") is not True:
            raise ValueError("reviewed_exact_desktop_identity_required")
        if entry.get("approval_kind") == "image_identity":
            if not entry.get("executable_path"):
                raise ValueError("desktop_image_path_required")
        elif entry.get("approval_kind") == "protected_os_identity":
            if not entry.get("review_note") or not entry.get("name") or not isinstance(entry.get("parent_identity"), dict):
                raise ValueError("protected_os_exact_review_required")
        else:
            raise ValueError("desktop_approval_kind_required")
    return receipt


def interpreter_metadata(python: Path, *, export=False):
    """仅stdlib包元数据；不导入torch/CUDA，不联网。"""
    code = r'''import sys,json,hashlib,pathlib,importlib.metadata as m,ctypes
from ctypes import wintypes
def h(p):
 with pathlib.Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read()).hexdigest()
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetCurrentProcess.restype=wintypes.HANDLE
k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
n=wintypes.DWORD(32768);b=ctypes.create_unicode_buffer(n.value)
if not k.QueryFullProcessImageNameW(k.GetCurrentProcess(),0,b,ctypes.byref(n)):raise RuntimeError('actual_interpreter_image_required')
actual=pathlib.Path(b.value).resolve()
packages={}
names=sorted({d.metadata['Name'] for d in m.distributions()}) if ALL_PACKAGES else []
for name in names:
 d=m.distribution(name)
 packages[name]={'version':d.version,'metadata_sha256':hashlib.sha256(d.read_text('METADATA').encode()).hexdigest(),'record_sha256':hashlib.sha256((d.read_text('RECORD') or '').encode()).hexdigest()}
runtime_dlls={p.name:h(p) for p in sorted(actual.parent.glob('python*.dll'))}
print(json.dumps({'version':sys.version.split()[0],'sys_executable':str(pathlib.Path(sys.executable).resolve()),'executable':str(actual),'executable_sha256':h(actual),'runtime_dlls':runtime_dlls,'packages':packages}))'''
    code = code.replace("ALL_PACKAGES", repr(export))
    result = subprocess.run([str(python), "-I", "-B", "-c", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=20, check=True)
    value = json.loads(result.stdout)
    value.update(launcher=str(python.resolve()), launcher_sha256=hashlib.sha256(python.read_bytes()).hexdigest())
    return value


class OuterJobQuery:
    """仅打开本次随机命名Job的查询权限；不获得其他进程停止权限。"""
    def __init__(self, name):
        if not re.fullmatch(r"ag-flow-[0-9a-f]{32}", name or ""):
            raise ValueError("owned_outer_job_name_required")
        self.kernel = k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k.OpenJobObjectW.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k.OpenJobObjectW(4, False, name)
        if not self.handle:
            raise OSError("owned_outer_job_query_required")
    def contains(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            member = wintypes.BOOL()
            return bool(self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(member)) and member.value)
        finally:
            self.kernel.CloseHandle(handle)
    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def snapshot(self):
        return read_job_snapshot(self.handle)


def classify(snapshot, baseline, *, is_own_pid, allowed_images):
    owned = []
    image_paths = {ntpath.normcase(path) for path in allowed_images}
    blockers = []
    for row in snapshot.get("processes", []):
        if is_own_pid(row["pid"]):
            if (row.get("identity_state") != "verified_image" or not row.get("creation_token")
                    or ntpath.normcase(row.get("executable_path") or "") not in image_paths
                    or row.get("context_type") not in {"G", "C", "C+G"}):
                blockers.append({"pid": row["pid"], "reason": "owned_job_image_or_context_not_bound"})
            owned.append(row["pid"])
    desktop = dict(snapshot, processes=[p for p in snapshot.get("processes", []) if p["pid"] not in owned])
    report = wddm.classify(desktop, baseline)
    if snapshot.get("driver_version") != baseline.get("driver_version"):
        blockers.append({"reason": "reviewed_driver_version_changed"})
    actual_ids = {p["pid"] for p in desktop.get("processes", [])}
    expected_ids = {p["pid"] for p in baseline.get("processes", [])}
    if actual_ids != expected_ids:
        blockers.append({"reason": "exact_desktop_process_set_changed"})
    report["blockers"].extend(blockers)
    report.update(allowed=not report["blockers"], owned_job_gpu_pids=owned, ownership_proof="IsProcessInJob_and_bound_image",
                  physical_gpu_exclusive=False, exact_desktop_set_required=True)
    return report


class AdmissionGuard:
    def __init__(self, payload, *, collector=None, job_query=None):
        self.payload = payload
        self.receipt_path = Path(payload["receipt_path"])
        self.query = job_query or OuterJobQuery(payload["outer_job_name"])
        self.collector = collector or wddm.collect_snapshot
        self.closed = False
    def check(self, phase, *, remaining=1):
        p = self.payload
        if digest(p["bindings"]) != p["bindings_sha256"]:
            raise ValueError("receipt_binding_payload_changed")
        owned = Path(p["checkout"])/"scripts/development/cosyvoice/acceleration"
        actual = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(owned.glob("*.py"))}
        if actual != p["bindings"]["own_sources"]:
            raise ValueError("candidate_source_bytes_changed_during_window")
        receipt = read_receipt(self.receipt_path, p["receipt_sha256"])
        validate_receipt(receipt, checkout=Path(p["checkout"]), output=Path(p["output"]), production=Path(p["production"]),
                         commit=p["commit"], bindings_sha256=p["bindings_sha256"], remaining=remaining)
        if not self.query.contains(os.getpid()):
            raise RuntimeError("controller_not_in_sole_owned_outer_job")
        bound = p["bindings"]
        images = [row[key] for row in bound["interpreters"].values() for key in ("executable", "launcher")]
        images.append(str((Path(bound["paths"]["sdk"])/"bin/trtexec.exe").resolve()))
        resources = self.query.snapshot()
        report = classify(self.collector(), receipt["shared_desktop_baseline"],
                          is_own_pid=self.query.contains, allowed_images=images)
        report["outer_job_resources"] = resources
        with (Path(p["output"]) / "window-checks.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(phase=phase, **report), ensure_ascii=False) + "\n")
        if not report["allowed"]:
            raise wddm.GPUWindowBlocked(report)
        return report
    def close(self):
        self.query.close()
        self.closed = True
