"""仅轻量CPU进程/合成采集器；不运行NVML、torch或真实模型。"""

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

PACKAGE = Path(__file__).resolve().parents[3]/"scripts/development/cosyvoice/acceleration"
spec = importlib.util.spec_from_file_location("ag_failure_acceleration", PACKAGE/"__init__.py", submodule_search_locations=[str(PACKAGE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
flow = importlib.import_module(spec.name+".flow_trtexec")
admission = importlib.import_module(spec.name+".window_admission")


@pytest.mark.skipif(sys.platform!="win32", reason="Windows owned Job accounting")
@pytest.mark.parametrize("mode", ["normal", "denied_commit", "exception"])
def test_real_cpu_job_keeps_peak_limits_and_counts_after_exit_and_termination(mode):
    # 超限测试一次请求2GiB > 1GiB Job硬限，必须立即拒绝；不实际提交大缓冲区。
    code = r'''import sys,json,ctypes
from ctypes import wintypes
sys.stdin.buffer.read()
buffer=bytearray(8*2**20)
result={'mode':sys.argv[1]}
if sys.argv[1]=='denied_commit':
 k=ctypes.WinDLL('kernel32',use_last_error=True)
 k.VirtualAlloc.argtypes=[ctypes.c_void_p,ctypes.c_size_t,wintypes.DWORD,wintypes.DWORD]
 k.VirtualAlloc.restype=ctypes.c_void_p
 pointer=k.VirtualAlloc(None,2*2**30,0x3000,4)
 result.update(allocation_denied=not bool(pointer),winerror=ctypes.get_last_error())
 if pointer:
  k.VirtualFree.argtypes=[ctypes.c_void_p,ctypes.c_size_t,wintypes.DWORD]
  k.VirtualFree(pointer,0,0x8000)
print(json.dumps(result),flush=True)
if sys.argv[1]=='exception':raise RuntimeError('synthetic_cpu_child_failure')
'''
    with flow.WindowsResourceJob(memory_limit_mib=1024) as job:
        child=subprocess.Popen([sys.executable,"-I","-B","-c",code,mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            job.assign(child)
            stdout,stderr=child.communicate(b"owned CPU only",timeout=10)
            report=json.loads(stdout)
            before=job.snapshot()
            assert before["active_processes"]==0 and before["total_processes"]>=1
            assert before["peak_job_memory_bytes"]>=8*2**20
            assert before["peak_process_memory_bytes"]>0
            assert before["job_memory_limit_bytes"]==1024*2**20
            assert before["affinity_mask"].bit_count()<=2
            assert before["cpu_user_time_100ns"]+before["cpu_kernel_time_100ns"]>0
            assert before["io_write_bytes"]>0
            if mode=="denied_commit":assert report["allocation_denied"] and report["winerror"]!=0
            if mode=="exception":assert child.returncode!=0 and b"synthetic_cpu_child_failure" in stderr
            else:assert child.returncode==0
            assert job.terminate_and_confirm()
            after=job.snapshot()
            assert after["active_processes"]==0
            assert after["peak_job_memory_bytes"]==before["peak_job_memory_bytes"]
            assert not after["memory_failure_cause_proven"]
        finally:
            if child.poll() is None:job.terminate_and_confirm()
            child.wait(timeout=5)


@pytest.mark.parametrize("exited", [23, 0, None])
def test_child_failure_and_external_context_refusal_are_both_preserved(monkeypatch,tmp_path,exited):
    class Process:
        pid=411
        returncode=None
        def poll(self):return self.returncode
        def kill(self):self.returncode=-9
        def wait(self,timeout):return self.returncode
    process=Process()
    class Guard:
        def check(self,phase,**kwargs):
            if phase.endswith(":running"):
                process.returncode=exited
                raise admission.wddm.GPUWindowBlocked({"blockers":[{"reason":"new_external_gpu_context"}]})
    monkeypatch.setattr(flow.subprocess,"Popen",lambda *a,**k:process)
    monkeypatch.setattr(flow,"gpu_memory",lambda:(0,16384))
    expected=flow.OwnedStageFailure if exited==23 else admission.wddm.GPUWindowBlocked
    with pytest.raises(expected) as error:
        flow.bounded(["CPU mock"],tmp_path,"export",{},10,gate=tmp_path/"gate",window_id="CPU-SYNTHETIC",
                     whole_deadline=time.perf_counter()+10,guard=Guard())
    evidence=json.loads((tmp_path/"export-exit.json").read_text())
    assert evidence["exit_code_observed_before_parent_stop"]==exited
    assert evidence["checkpoint_error"]["type"]=="GPUWindowBlocked"
    if exited==23:assert error.value.concurrent_error["type"]=="GPUWindowBlocked"
    assert evidence["parent_stopped_live_entry"] is (exited is None)
    assert evidence["final_exit_code"]==(exited if exited is not None else -9)
