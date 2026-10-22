"""SDK11 worker的真实服务适配：仅Flow走引擎，其余语音与角色状态保留。"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import struct
import subprocess
import threading


class NativeFlowWorker:
    def __init__(self, *, engine_path, worker_path, sdk_root, toolkit_root, timeout_seconds=30):
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join((str(Path(sdk_root)/"bin"), str(Path(toolkit_root)/"bin/x64"), env.get("PATH", "")))
        self.process = subprocess.Popen([str(worker_path),str(engine_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL,env=env)
        self.timeout = timeout_seconds
        self.lock = threading.Lock()
        self.reader = ThreadPoolExecutor(max_workers=1,thread_name_prefix="flow-trt11")
        try:
            self._receive(b"RDY1", 60)
        except BaseException:
            self.close()
            raise

    def _read_exact(self, size):
        value = bytearray()
        while len(value) < size:
            block = self.process.stdout.read(size-len(value))
            if not block:
                raise RuntimeError("TensorRT worker exited")
            value.extend(block)
        return bytes(value)

    def _receive(self, expected_magic, timeout):
        def read():
            magic,status,size = struct.unpack("<4sII",self._read_exact(12))
            if magic != expected_magic or size > 2**20:
                raise RuntimeError("invalid TensorRT worker response")
            data = self._read_exact(size)
            if status:
                raise RuntimeError(data.decode("utf-8",errors="replace"))
            return data
        return self.reader.submit(read).result(timeout=timeout)

    def infer(self, values):
        n = int(values[0].shape[2])
        with self.lock:
            try:
                self.process.stdin.write(struct.pack("<4sI",b"FLW1",n))
                for value in values:
                    self.process.stdin.write(memoryview(value).cast("B"))
                self.process.stdin.flush()
                data = self._receive(b"FLW1",self.timeout)
            except BaseException:
                self.close()
                raise
        import numpy as np
        result = np.frombuffer(data,dtype="<f4").reshape(2,80,n)
        if not np.isfinite(result).all():
            raise RuntimeError("nonfinite TensorRT Flow output")
        return result.copy()

    def close(self):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        for stream in (self.process.stdin,self.process.stdout):
            if stream is not None:
                stream.close()
        self.reader.shutdown(wait=False,cancel_futures=True)


class FlowAdapter:
    def __init__(self, owner, original, candidate, worker):
        self.owner,self.original,self.candidate,self.worker = owner,original,candidate,worker
        self.applied,self.reason = True,"flow_trt11_worker_installed"

    def restore(self):
        restored = self.owner.estimator is self.candidate
        if restored:
            self.owner.estimator = self.original
        self.worker.close()
        self.applied = False
        return restored


def install_flow_trt11_worker(runtime_model, *, engine_path, worker_path, sdk_root, toolkit_root, graph_streaming=True):
    """由ROOT在候选实例启动时调用；当前签名不改AD服务或已运行实例。"""
    import torch
    owner = runtime_model.flow.decoder
    original = owner.estimator
    worker = NativeFlowWorker(engine_path=engine_path,worker_path=worker_path,sdk_root=sdk_root,toolkit_root=toolkit_root)
    class Estimator(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.original = original
            self.native_failed = False
        def forward(self,x,mask,mu,t,spks=None,cond=None,streaming=False):
            n = x.shape[2]
            if self.native_failed or streaming is not graph_streaming or x.shape[0] != 2 or not 16 <= n <= 512:
                return self.original(x,mask,mu,t,spks,cond,streaming=streaming)
            try:
                values = [value.detach().to(device="cpu",dtype=torch.float32).contiguous().numpy() for value in (x,mask,mu,t,spks,cond)]
                result = worker.infer(values)
                return torch.from_numpy(result).to(device=x.device,dtype=x.dtype)
            except Exception:
                self.native_failed = True
                worker.close()
                return self.original(x,mask,mu,t,spks,cond,streaming=streaming)
    candidate = Estimator().eval()
    owner.estimator = candidate
    return FlowAdapter(owner,original,candidate,worker)
