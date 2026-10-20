"""AG准入拒绝与唯一外层Job：合成收据/快照，绝不调用NVML或GPU模型。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "scripts/development/cosyvoice/acceleration"
spec = importlib.util.spec_from_file_location("ag_window_acceleration", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
gate = importlib.import_module("ag_window_acceleration.window_admission")
flow = importlib.import_module("ag_window_acceleration.flow_trtexec")


def fixture_receipt(tmp_path):
    now = datetime.now(timezone.utc)
    image = dict(pid=51, creation_token="filetime:123", executable_path="D:/Apps/desktop.exe", context_type="C+G",
                 identity_state="verified_image", background_only=True, approval_kind="image_identity")
    baseline = dict(gpu_uuid="GPU-synthetic", driver_model="WDDM", driver_version="synthetic-driver", reviewed_by="main_session", reviewed_at_utc=(now-timedelta(seconds=5)).isoformat(), processes=[image])
    paths = dict(checkout=tmp_path/"checkout", production=tmp_path/"production", output=tmp_path/"checkout/experiments/runs/unique")
    bindings = {"own_sources": {}}
    receipt = dict(schema_version=2, scope=gate.SCOPE, state="active", issued_by="main_session", window_id="AG-FLOW-GPU-SYNTHETIC-01",
                   project_model_window=True, production_stopped=True, other_gpu_model_workers_stopped=True, physical_gpu_exclusive=False,
                   candidate_commit="a"*40, bindings_sha256=gate.digest(bindings), max_seconds=1320,
                   checkout=str(paths["checkout"]), production_root=str(paths["production"]), output=str(paths["output"]),
                   issued_at_utc=(now-timedelta(seconds=1)).isoformat(), expires_at_utc=(now+timedelta(seconds=1500)).isoformat(),
                   shared_desktop_baseline=baseline, desktop_baseline_sha256=gate.digest(baseline))
    kwargs = dict(**paths, commit="a"*40, bindings_sha256=gate.digest(bindings), now=now)
    return receipt, kwargs, bindings


def test_exact_v2_window_is_project_scope_and_requires_remaining_time(tmp_path):
    receipt, kwargs, _ = fixture_receipt(tmp_path)
    assert gate.validate_receipt(receipt, **kwargs) is receipt
    assert receipt["physical_gpu_exclusive"] is False


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("scope", "ad-cosy-project-model-window"), ("state", "closed"),
    ("issued_by", "worker"), ("production_stopped", False), ("other_gpu_model_workers_stopped", False),
    ("physical_gpu_exclusive", True), ("candidate_commit", "b"*40), ("bindings_sha256", "c"*64),
    ("max_seconds", 480), ("window_id", "arbitrary-id"), ("checkout", ""), ("production_root", ""), ("output", ""),
    ("expires_at_utc", "2000-01-01T00:00:00Z"), ("issued_at_utc", "2099-01-01T00:00:00Z"),
    ("desktop_baseline_sha256", "0"*64),
])
def test_drift_expired_or_closed_receipts_rejected(tmp_path, field, value):
    receipt, kwargs, _ = fixture_receipt(tmp_path)
    receipt[field] = value
    with pytest.raises(ValueError):
        gate.validate_receipt(receipt, **kwargs)


@pytest.mark.parametrize("window", ["AD-GPU-20261021-01", "AG-FLOW-GPU-20261021-01"])
def test_closed_id_is_explicitly_rejected_even_with_new_dates(tmp_path, window):
    receipt, kwargs, _ = fixture_receipt(tmp_path)
    receipt["window_id"] = window
    with pytest.raises(ValueError, match="closed_window"):
        gate.validate_receipt(receipt, **kwargs)


def test_naive_expiry_stale_review_and_duplicate_pid_rejected(tmp_path):
    for change in ("naive", "stale", "review_after_issue", "duplicate"):
        receipt, kwargs, _ = fixture_receipt(tmp_path)
        if change == "naive":
            receipt["expires_at_utc"] = "2099-01-01T00:00:00"
        elif change == "stale":
            receipt["shared_desktop_baseline"]["reviewed_at_utc"] = "2000-01-01T00:00:00Z"
        elif change == "review_after_issue":
            receipt["shared_desktop_baseline"]["reviewed_at_utc"] = kwargs["now"].isoformat()
        else:
            receipt["shared_desktop_baseline"]["processes"] *= 2
        receipt["desktop_baseline_sha256"] = gate.digest(receipt["shared_desktop_baseline"])
        with pytest.raises(ValueError):
            gate.validate_receipt(receipt, **kwargs)


def test_receipt_bytes_changed_cannot_be_used(tmp_path):
    receipt, _, _ = fixture_receipt(tmp_path)
    path = tmp_path/"receipt.json"
    raw = json.dumps(receipt).encode()
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    assert gate.read_receipt(path, sha)["state"] == "active"
    receipt["state"] = "closed"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="revoked"):
        gate.read_receipt(path, sha)


def snapshot_for(receipt):
    return dict(gpu_uuid="GPU-synthetic", driver_model="WDDM", driver_version="synthetic-driver", processes=deepcopy(receipt["shared_desktop_baseline"]["processes"]))


@pytest.mark.parametrize("drift", ["unknown_cg", "compute", "pid_reused", "image_changed", "unresolved", "missing_desktop", "wrong_gpu", "driver_changed"])
def test_unknown_or_changed_gpu_owner_fails_closed(tmp_path, drift):
    receipt, _, _ = fixture_receipt(tmp_path)
    snapshot = snapshot_for(receipt)
    row = snapshot["processes"][0]
    if drift == "unknown_cg":
        snapshot["processes"].append(dict(row, pid=999))
    elif drift == "compute":
        row["context_type"] = "C"
    elif drift == "pid_reused":
        row["creation_token"] = "filetime:456"
    elif drift == "image_changed":
        row["executable_path"] = "D:/Apps/other.exe"
    elif drift == "unresolved":
        row["identity_state"] = "unresolved"
    elif drift == "missing_desktop":
        snapshot["processes"] = []
    elif drift == "wrong_gpu":
        snapshot["gpu_uuid"] = "GPU-other"
    else:
        snapshot["driver_version"] = "changed"
    report = gate.classify(snapshot, receipt["shared_desktop_baseline"], is_own_pid=lambda _: False, allowed_images=[])
    assert not report["allowed"] and not report["physical_gpu_exclusive"]


def test_only_job_member_with_bound_image_can_be_gpu_worker(tmp_path):
    receipt, _, _ = fixture_receipt(tmp_path)
    snapshot = snapshot_for(receipt)
    snapshot["processes"].append(dict(pid=99, context_type="C", creation_token="filetime:99", executable_path="D:/Python/python.exe", identity_state="verified_image"))
    args = dict(snapshot=snapshot, baseline=receipt["shared_desktop_baseline"], allowed_images=["D:/Python/python.exe"])
    assert not gate.classify(**args, is_own_pid=lambda _: False)["allowed"]
    assert gate.classify(**args, is_own_pid=lambda pid: pid == 99)["allowed"]
    assert not gate.classify(snapshot, receipt["shared_desktop_baseline"], is_own_pid=lambda pid: pid == 99, allowed_images=[])["allowed"]


@pytest.mark.parametrize("failure", ["timeout", "assign"])
@pytest.mark.parametrize("snapshot_failure", [False, True])
def test_execute_has_one_outer_job_before_permission_and_terminates_all(monkeypatch, tmp_path, failure, snapshot_failure):
    receipt, kwargs, bindings = fixture_receipt(tmp_path)
    root = kwargs["checkout"]
    monkeypatch.setattr(flow, "ROOT", root)
    monkeypatch.setattr(flow, "_git_state", lambda: ("a"*40, True))
    monkeypatch.setattr(flow, "bindings_plan", lambda *a: dict(resources_match=True, export_environment_compatible=True, bindings_sha256=gate.digest(bindings), bindings=dict(bindings, interpreters={"controller":dict(executable="D:/P/python.exe",launcher="D:/P/python.exe"),"export":dict(executable="D:/C/python.exe",launcher="D:/C/python.exe")})))
    monkeypatch.setattr(flow, "gpu_memory", lambda: pytest.fail("parent must not probe GPU"))
    path = tmp_path/"receipt.json"; raw=json.dumps(receipt).encode(); path.write_bytes(raw)
    actions=[]
    class Job:
        def __init__(self, **k):actions.append("one_outer_job")
        def __enter__(self):return self
        def __exit__(self,*a):actions.append("context_closed")
        def assign(self,p):
            actions.append("assigned")
            if failure=="assign":raise OSError("mock assign failure")
        def terminate_and_confirm(self):actions.append("terminated_tree");return True
        def snapshot(self):
            if snapshot_failure:raise OSError("synthetic query failure")
            return dict(active_processes=0, peak_job_memory_bytes=1234, job_memory_limit_bytes=6144*2**20)
        def close(self):actions.append("closed")
    class Process:
        returncode=None
        def communicate(self,payload,timeout):
            actions.append("permission_sent")
            assert 0<timeout<=1320
            raise subprocess.TimeoutExpired("owned_mock_controller",timeout)
        def poll(self):return self.returncode
        def kill(self):actions.append("unassigned_entry_killed");self.returncode=1
        def wait(self,timeout):actions.append("reaped");self.returncode=1
    monkeypatch.setattr(flow,"WindowsResourceJob",Job)
    monkeypatch.setattr(flow.subprocess,"Popen",lambda *a,**k:Process())
    production=kwargs["production"];source=production/"local/runtime/CosyVoice"
    with pytest.raises((subprocess.TimeoutExpired,OSError)):
        flow.execute(source,tmp_path/"model",tmp_path/"sdk",tmp_path/"toolkit",kwargs["output"],source/".venv/Scripts/python.exe",
                     receipt_path=path,receipt_sha256=hashlib.sha256(raw).hexdigest(),production_root=production)
    assert actions.count("one_outer_job")==1 and "terminated_tree" in actions and "reaped" in actions
    resources=json.loads((kwargs["output"]/"outer-job-resources.json").read_text())
    if snapshot_failure:assert len(resources["errors"])==2
    else:
        assert resources["before_termination"]["peak_job_memory_bytes"]==1234
        assert resources["after_termination"]["active_processes"]==0
    assert resources["entry_error"]
    if failure=="assign":assert "permission_sent" not in actions
    else:assert actions.index("assigned")<actions.index("permission_sent")<actions.index("terminated_tree")


@pytest.mark.skipif(sys.platform!="win32",reason="Windows Job query")
def test_named_outer_job_membership_uses_actual_interpreter_pid(tmp_path):
    name="ag-flow-"+uuid.uuid4().hex
    code="import sys,os,json; sys.path.insert(0,sys.argv[1]); from acceleration.window_admission import OuterJobQuery; sys.stdin.buffer.read(); q=OuterJobQuery(sys.argv[2]); print(json.dumps({'member':q.contains(os.getpid()),'resources':q.snapshot()})); q.close()"
    with flow.WindowsResourceJob(memory_limit_mib=6144,job_name=name) as job:
        process=subprocess.Popen([sys.executable,"-I","-B","-c",code,str(PACKAGE.parent),name],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            job.assign(process)
            out,_=process.communicate(b"CPU mock only",timeout=5)
            assert json.loads(out)["member"]
            assert json.loads(out)["resources"]["job_memory_limit_bytes"]==6144*2**20
            assert job.terminate_and_confirm()
        finally:
            if process.poll() is None:job.terminate_and_confirm()
            process.wait(timeout=5)


@pytest.mark.parametrize("failure", ["expired", "closed_ad", "wrong_scope", "revoked"])
def test_execute_rejects_before_interpreter_probe_or_gpu_or_job(monkeypatch, tmp_path, failure):
    receipt, kwargs, _ = fixture_receipt(tmp_path)
    monkeypatch.setattr(flow, "ROOT", kwargs["checkout"])
    monkeypatch.setattr(flow, "_git_state", lambda: ("a"*40, True))
    for name in ("bindings_plan", "gpu_memory", "WindowsResourceJob"):
        monkeypatch.setattr(flow, name, lambda *a, **k: pytest.fail("must reject before runtime probing/Job"))
    if failure == "expired":receipt["expires_at_utc"]="2000-01-01T00:00:00Z"
    elif failure == "closed_ad":receipt["window_id"]="AD-GPU-20261021-01"
    elif failure == "wrong_scope":receipt["scope"]="ad-cosy-project-model-window"
    path=tmp_path/"receipt.json";raw=json.dumps(receipt).encode();path.write_bytes(raw)
    sha=hashlib.sha256(raw).hexdigest()
    if failure=="revoked":path.write_bytes(raw+b" ")
    source=kwargs["production"]/"local/runtime/CosyVoice"
    with pytest.raises(ValueError):
        flow.execute(source,tmp_path/"model",tmp_path/"sdk",tmp_path/"toolkit",kwargs["output"],source/".venv/Scripts/python.exe",
                     receipt_path=path,receipt_sha256=sha,production_root=kwargs["production"])


def test_execute_dependency_digest_drift_rejected_before_outer_job(monkeypatch, tmp_path):
    receipt, kwargs, _ = fixture_receipt(tmp_path)
    monkeypatch.setattr(flow,"ROOT",kwargs["checkout"])
    monkeypatch.setattr(flow,"_git_state",lambda:("a"*40,True))
    monkeypatch.setattr(flow,"bindings_plan",lambda *a:dict(resources_match=True,export_environment_compatible=True,bindings_sha256="f"*64))
    monkeypatch.setattr(flow,"WindowsResourceJob",lambda **k:pytest.fail("must not create Job"))
    monkeypatch.setattr(flow,"gpu_memory",lambda:pytest.fail("must not probe GPU"))
    path=tmp_path/"receipt.json";raw=json.dumps(receipt).encode();path.write_bytes(raw)
    source=kwargs["production"]/"local/runtime/CosyVoice"
    with pytest.raises(ValueError,match="dependency_digest"):
        flow.execute(source,tmp_path/"model",tmp_path/"sdk",tmp_path/"toolkit",kwargs["output"],source/".venv/Scripts/python.exe",
                     receipt_path=path,receipt_sha256=hashlib.sha256(raw).hexdigest(),production_root=kwargs["production"])


def test_guard_rechecks_source_and_receipt_before_snapshot(monkeypatch, tmp_path):
    receipt, kwargs, bindings=fixture_receipt(tmp_path)
    owned=kwargs["checkout"]/"scripts/development/cosyvoice/acceleration"
    owned.mkdir(parents=True)
    source=owned/"owned.py";source.write_bytes(b"original")
    bindings["own_sources"]={"owned.py":hashlib.sha256(b"original").hexdigest()}
    bindings.update(interpreters={},paths={"sdk":str(tmp_path/"sdk")})
    receipt["bindings_sha256"]=gate.digest(bindings)
    path=tmp_path/"receipt.json";raw=json.dumps(receipt).encode();path.write_bytes(raw)
    kwargs["output"].mkdir(parents=True)
    payload=dict(checkout=str(kwargs["checkout"]),output=str(kwargs["output"]),production=str(kwargs["production"]),commit="a"*40,
                 receipt_path=str(path),receipt_sha256=hashlib.sha256(raw).hexdigest(),bindings=bindings,bindings_sha256=gate.digest(bindings),allowed_images=[])
    snapshots=[]
    def collect():snapshots.append(True);return snapshot_for(receipt)
    class Query:
        def contains(self,pid):return pid==gate.os.getpid()
        def snapshot(self):return {"peak_job_memory_bytes":1234}
        def close(self):pass
    proof=gate.AdmissionGuard(payload,collector=collect,job_query=Query())
    assert proof.check("first")["allowed"]
    source.write_bytes(b"changed")
    with pytest.raises(ValueError,match="source_bytes_changed"):
        proof.check("after edit")
    assert len(snapshots)==1
    source.write_bytes(b"original")
    path.write_bytes(raw+b" ")
    with pytest.raises(ValueError,match="revoked"):
        proof.check("after revoke")
    assert len(snapshots)==1
    proof.close()


@pytest.mark.skipif(sys.platform!="win32",reason="Windows interpreter image query")
def test_interpreter_metadata_is_stdlib_only_and_binds_actual_image():
    metadata=gate.interpreter_metadata(Path(sys.executable))
    assert metadata["packages"]=={}
    assert len(metadata["executable_sha256"])==64 and len(metadata["launcher_sha256"])==64
    assert metadata["runtime_dlls"]


@pytest.mark.skipif(sys.platform!="win32",reason="Windows Job termination with query handle")
def test_outer_termination_reaps_child_that_still_holds_query_handle(tmp_path):
    name="ag-flow-"+uuid.uuid4().hex
    ready=tmp_path/"query-held"
    code="import sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from acceleration.window_admission import OuterJobQuery; sys.stdin.buffer.read(); q=OuterJobQuery(sys.argv[2]); Path(sys.argv[3]).write_text('ready'); time.sleep(20)"
    with flow.WindowsResourceJob(memory_limit_mib=6144,job_name=name) as job:
        process=subprocess.Popen([sys.executable,"-I","-B","-c",code,str(PACKAGE.parent),name,str(ready)],stdin=subprocess.PIPE)
        try:
            job.assign(process)
            process.stdin.write(b"only own CPU child")
            process.stdin.close()
            until=time.monotonic()+4
            while not ready.exists() and time.monotonic()<until:time.sleep(.02)
            assert ready.exists()
            assert job.terminate_and_confirm(timeout=3)
            process.wait(timeout=3)
        finally:
            if process.poll() is None:job.terminate_and_confirm(timeout=3)
            process.wait(timeout=3)
