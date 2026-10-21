"""固定环境已有时在受限CPU子进程跑ONNX/ORT契约，不安装任何依赖。"""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
PACKAGE=ROOT/"scripts/development/cosyvoice/acceleration"
spec=importlib.util.spec_from_file_location("ag_external_acceleration",PACKAGE/"__init__.py",submodule_search_locations=[str(PACKAGE)])
package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
job_module=__import__(spec.name+".bge_benchmark",fromlist=["WindowsResourceJob"])


def test_import_does_not_load_inference_libraries():
    code="import sys;sys.path.insert(0,sys.argv[1]);import acceleration.external_weights;assert not any(x in sys.modules for x in ['torch','onnx','onnxruntime','numpy'])"
    subprocess.run([sys.executable,"-I","-B","-c",code,str(PACKAGE.parent)],check=True,cwd=ROOT)


def test_controller_hash_verification_needs_only_stdlib(tmp_path):
    external=__import__(spec.name+".external_weights",fromlist=["verify_bundle_files"])
    (tmp_path/"model.onnx").write_bytes(b"opaque_graph_bytes")
    (tmp_path/"weights.bin").write_bytes(b"1234")
    manifest=dict(schema_version=1,recipe=external.RECIPE,graph=dict(file="model.onnx",bytes=18,sha256=hashlib.sha256(b"opaque_graph_bytes").hexdigest()),
                  data=dict(file="weights.bin",bytes=4,sha256=hashlib.sha256(b"1234").hexdigest()))
    raw=json.dumps(manifest).encode();(tmp_path/"manifest.json").write_bytes(raw)
    assert "onnx" not in sys.modules
    assert external.verify_bundle_files(tmp_path,hashlib.sha256(raw).hexdigest())==manifest
    assert "onnx" not in sys.modules


@pytest.mark.skipif(sys.platform!="win32",reason="uses existing fixed Windows Cosy environment and owned CPU Job")
def test_fixed_environment_cpu_suite(tmp_path):
    python=ROOT.parents[2]/"local/runtime/CosyVoice/.venv/Scripts/python.exe"
    if not python.is_file():pytest.skip("fixed Cosy environment unavailable; no installation")
    fixture=ROOT/"tests/fixtures/external_weights_cpu_suite.py"
    env=dict(os.environ,CUDA_VISIBLE_DEVICES="",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",OMP_NUM_THREADS="2",MKL_NUM_THREADS="2",TMP=str(tmp_path),TEMP=str(tmp_path))
    with job_module.WindowsResourceJob(memory_limit_mib=2048) as job:
        child=subprocess.Popen([str(python),"-I","-B",str(fixture),str(PACKAGE.parent),str(tmp_path)],cwd=ROOT,env=env,
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            job.assign(child)
            stdout,stderr=child.communicate(b"CPU micro-model suite only",timeout=60)
            assert child.returncode==0,stderr.decode("utf-8",errors="replace")
            report=json.loads((tmp_path/"cpu-suite.json").read_text())
            assert report["tests_run"]==15 and not report["errors"] and not report["failures"]
            assert not report["cuda_initialized"] and not report["real_flow_loaded"]
            assert job.snapshot()["peak_job_memory_bytes"]>0
        finally:
            assert job.terminate_and_confirm()
            child.wait(timeout=5)
            assert job.snapshot()["active_processes"]==0
