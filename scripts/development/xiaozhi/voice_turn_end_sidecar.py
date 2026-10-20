"""常驻独立 CPU 话轮模型进程，私有匿名管道通信，不监听网络端口。

启动/关闭由组合层管理；predict 只可从 InferenceSlot 的线程调用。
不会在音频热路径建进程。超时关闭本对象创建的进程，不重试或重启。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.metadata
import json
import math
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time


HEADER = struct.Struct("!4sQI")
MAGIC = b"STE1"
MAX_PCM_BYTES = 256000
MAX_REPLY_BYTES = 4096
CPU_ENV = {"USE_TORCH": "0", "USE_TF": "0", "USE_FLAX": "0",
           "CUDA_VISIBLE_DEVICES": "-1", "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "OMP_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
           "TOKENIZERS_PARALLELISM": "false", "PYTHONDONTWRITEBYTECODE": "1"}


def cpu_environment():
    # 不继承跨项目拼包路径；只修改即将创建的专有子进程环境。
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"}}
    environment.update(CPU_ENV)
    return environment


def _read_exact(stream, size):
    pieces = []
    while size:
        piece = stream.read(size)
        if not piece:
            raise EOFError("turn_end_pipe_eof")
        pieces.append(piece)
        size -= len(piece)
    return b"".join(pieces)


def _reply(stream, message):
    encoded = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"
    if len(encoded) > MAX_REPLY_BYTES:
        raise ValueError("turn_end_reply_budget")
    stream.write(encoded)
    stream.flush()


def _read_reply(stream):
    line = stream.readline(MAX_REPLY_BYTES + 1)
    if not line or len(line) > MAX_REPLY_BYTES or not line.endswith(b"\n"):
        raise ValueError("turn_end_invalid_reply")
    value = json.loads(line)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("turn_end_reply_version")
    return value


def worker_loop(detector, source, sink):
    """可注入合成模型的固定二进制协议，正文不进入异常或日志。"""
    _reply(sink, {"version": 1, "status": "ready", "provider": "CPUExecutionProvider"})
    while True:
        try:
            header = _read_exact(source, HEADER.size)
        except EOFError:
            return 0
        magic, sequence, size = HEADER.unpack(header)
        if magic != MAGIC or not 0 < size <= MAX_PCM_BYTES or size % 2:
            return 2
        try:
            pcm = _read_exact(source, size)
        except EOFError:
            return 2
        started = time.perf_counter()
        try:
            probability = detector.predict(pcm)
            if type(probability) not in {float, int} or not math.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("invalid_probability")
            _reply(sink, {"version": 1, "id": sequence, "status": "ok",
                          "probability": probability,
                          "processing_ms": round((time.perf_counter() - started) * 1000, 3)})
        except Exception:
            _reply(sink, {"version": 1, "id": sequence, "status": "error", "reason": "inference_failed"})


class _Job:
    def __init__(self, sequence, pcm):
        self.sequence, self.pcm = sequence, pcm
        self.done = threading.Event()
        self.reply = None
        self.error = False


class SidecarDetector:
    """启动一次、最多一个请求，150ms 总预算内的匿名管道模型适配器。

    构造可能冷启动数秒，服务应 await create(...) 后才宣告就绪；不要在帧中构造。
    专属 I/O 线程负责阻塞管道，音频事件循环从不读写管道。超时结果永不复用。
    """

    def __init__(self, python, model, *, startup_timeout=30.0, request_timeout_ms=120,
                 _command=None, _cancel_startup=None):
        if not 1 <= startup_timeout <= 60 or not 10 <= request_timeout_ms <= 500:
            raise ValueError("turn_end_sidecar_budget")
        self.request_timeout = request_timeout_ms / 1000
        self.jobs = queue.Queue(maxsize=1)
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.serial = threading.Lock()
        self.sequence = 0
        self.ready_ok = False
        self.latest_processing_ms = None
        self.counts = {"completed": 0, "timeout": 0, "failed": 0, "busy": 0}
        command = _command or [str(Path(python).resolve()), "-I", "-B", "-u",
                               str(Path(__file__).resolve()), "--worker", "--model", str(Path(model).resolve())]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=cpu_environment(),
                                        cwd=str(Path(__file__).resolve().parent), **options)
        self.io_thread = threading.Thread(target=self._io_loop, name="turn-end-cpu-pipe", daemon=True)
        self.io_thread.start()
        deadline = time.monotonic() + startup_timeout
        while not self.ready.wait(min(0.05, max(0, deadline - time.monotonic()))):
            if time.monotonic() >= deadline or (_cancel_startup is not None and _cancel_startup.is_set()):
                break
        if (not self.ready.is_set() or not self.ready_ok
                or (_cancel_startup is not None and _cancel_startup.is_set())):
            self.close()
            raise RuntimeError("turn_end_sidecar_unavailable")

    @classmethod
    async def create(cls, python, model, **kwargs):
        cancel = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(cls, python, model, _cancel_startup=cancel, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            # 构造线程收到取消后回收其专属进程；迟到异常不写默认日志。
            def reap(done):
                try:
                    value = done.result()
                except BaseException:
                    return
                # 构造刚完成而调用方恰被取消时，也不能遗留已就绪子进程。
                threading.Thread(target=value.close, name="turn-end-cancel-reap", daemon=True).start()
            task.add_done_callback(reap)
            raise

    def _disable(self):
        self.stopped.set()
        if self.process.poll() is None:
            try:
                self.process.terminate()  # 仅本对象拥有的进程句柄，不按名称或端口找服务。
            except OSError:
                pass

    def _io_loop(self):
        job = None
        try:
            handshake = _read_reply(self.process.stdout)
            self.ready_ok = (handshake.get("status") == "ready"
                             and handshake.get("provider") == "CPUExecutionProvider")
            self.ready.set()
            if not self.ready_ok:
                return
            while not self.stopped.is_set():
                try:
                    job = self.jobs.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.process.stdin.write(HEADER.pack(MAGIC, job.sequence, len(job.pcm)))
                self.process.stdin.write(job.pcm)
                self.process.stdin.flush()
                job.pcm = b""
                response = _read_reply(self.process.stdout)
                if response.get("id") != job.sequence or response.get("status") != "ok":
                    raise ValueError("turn_end_sidecar_request_failed")
                value = response.get("probability")
                duration = response.get("processing_ms")
                if (type(value) not in {float, int} or not math.isfinite(value) or not 0 <= value <= 1
                        or type(duration) not in {float, int} or not math.isfinite(duration) or duration < 0):
                    raise ValueError("turn_end_sidecar_invalid_result")
                job.reply = response
                job.done.set()
                job = None
        except Exception:
            if job is not None:
                job.error = True
                job.pcm = b""
                job.done.set()
        finally:
            self.ready.set()
            self._disable()

    def predict(self, pcm):
        if not isinstance(pcm, bytes) or not 0 < len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
            raise ValueError("turn_end_sidecar_pcm_budget")
        if self.stopped.is_set():
            raise RuntimeError("turn_end_sidecar_disabled")
        if not self.serial.acquire(blocking=False):
            self.counts["busy"] += 1
            raise RuntimeError("turn_end_sidecar_busy")
        try:
            self.sequence += 1
            job = _Job(self.sequence, pcm)
            self.jobs.put_nowait(job)
            if not job.done.wait(self.request_timeout):
                self.counts["timeout"] += 1
                self._disable()
                raise TimeoutError("turn_end_sidecar_timeout")
            if job.error or self.stopped.is_set():
                self.counts["failed"] += 1
                raise RuntimeError("turn_end_sidecar_failed")
            self.latest_processing_ms = job.reply["processing_ms"]
            self.counts["completed"] += 1
            return float(job.reply["probability"])
        finally:
            self.serial.release()

    def snapshot(self):
        return {"version": 1, "backend": "cpu_pipe", "ready": self.ready_ok and not self.stopped.is_set(),
                "latest_processing_ms": self.latest_processing_ms, **self.counts}

    def close(self):
        self._disable()
        while True:
            try:
                pending = self.jobs.get_nowait()
            except queue.Empty:
                break
            pending.pcm = b""
            pending.error = True
            pending.done.set()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if threading.current_thread() is not self.io_thread:
            self.io_thread.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass

    async def aclose(self):
        await asyncio.to_thread(self.close)


def feature_probe(*, reference_torch=False):
    """固定非语音 PCM 特征供逐项比较；不输出文件，不加载 ONNX 或 GPU。"""
    import numpy as np
    from transformers import WhisperFeatureExtractor
    from voice_turn_end_model import extract_features

    if "torch" in sys.modules and not reference_torch:
        raise RuntimeError("turn_end_probe_imported_torch")
    extractor = WhisperFeatureExtractor(chunk_length=8)
    rng = np.random.RandomState(196)
    cases = {"silence": np.zeros(4000, dtype="<i2"),
             "extremes": np.array([-32768, 32767, -1, 0, 1] * 192, dtype="<i2"),
             "tone": (np.sin(np.arange(16000) * (2 * np.pi * 440 / 16000)) * 12000).astype("<i2"),
             "eight_seconds": rng.randint(-20000, 20000, 128000).astype("<i2"),
             "truncate_ten_seconds": rng.randint(-20000, 20000, 160000).astype("<i2")}
    features = {}
    for name, audio in cases.items():
        value = extract_features(audio.tobytes(), np, extractor)
        features[name] = {"shape": list(value.shape),
                          "float32le_base64": base64.b64encode(value.astype("<f4").tobytes()).decode("ascii")}
    return {"version": 1, "python": sys.version.split()[0],
            "versions": {name: importlib.metadata.version(name) for name in ("numpy", "transformers")},
            "torch_imported": "torch" in sys.modules, "features": features}


def compare_features(candidate_python):
    """与本解释器官方 NumPy/CPU Torch 特征逐元素比对，不需要模型。"""
    import numpy as np
    script = str(Path(__file__).resolve())
    commands = {"candidate_numpy": [str(Path(candidate_python).resolve()), "-I", "-B", script, "--feature-probe"],
                "reference_numpy": [sys.executable, "-I", "-B", script, "--feature-probe"],
                "reference_torch_cpu": [sys.executable, "-I", "-B", script, "--feature-probe", "--reference-torch-features"]}
    probes = {}
    for name, command in commands.items():
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=cpu_environment(), timeout=45, check=False)
        if result.returncode or len(result.stdout) > 3000000:
            raise RuntimeError("turn_end_feature_probe_failed")
        probes[name] = json.loads(result.stdout)
    comparisons = {}
    for name, candidate in probes["candidate_numpy"]["features"].items():
        left = np.frombuffer(base64.b64decode(candidate["float32le_base64"]), dtype="<f4")
        comparisons[name] = {}
        for reference in ("reference_numpy", "reference_torch_cpu"):
            right_item = probes[reference]["features"][name]
            right = np.frombuffer(base64.b64decode(right_item["float32le_base64"]), dtype="<f4")
            delta = np.abs(left - right)
            comparisons[name][reference] = {
                "elements": left.size, "shape": candidate["shape"],
                "max_abs": float(delta.max()), "mean_abs": float(delta.mean()),
                "allclose_1e_5": candidate["shape"] == right_item["shape"] and bool(np.allclose(left, right, rtol=1e-5, atol=1e-5))}
    return {"version": 1, "evidence": "synthetic_pcm_official_feature_numeric_comparison",
            "runtimes": {name: {field: result[field] for field in ("python", "versions", "torch_imported")}
                         for name, result in probes.items()}, "comparisons": comparisons,
            "model_compatibility": "not_tested"}


def main():
    # -I 不会加入脚本目录；这里只加本项目自有模块目录，不拼接其他环境的包。
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.update(CPU_ENV)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--feature-probe", action="store_true")
    parser.add_argument("--reference-torch-features", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--compare-python", type=Path, help="与已有纯CPU Torch参考解释器逐元素比较")
    parser.add_argument("--probe-model", action="store_true")
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    if args.compare_python:
        print(json.dumps(compare_features(args.compare_python), indent=2))
        return 0
    if args.reference_torch_features:
        if not args.feature_probe or not importlib.metadata.version("torch").endswith("+cpu"):
            parser.error("reference requires a CPU-only Torch distribution and --feature-probe")
        os.environ["USE_TORCH"] = "1"
    if args.feature_probe:
        print(json.dumps(feature_probe(reference_torch=args.reference_torch_features), separators=(",", ":")))
        return 0
    if args.model is None:
        parser.error("--model required")
    try:
        from voice_turn_end_model import SmartTurnCPU, MODEL_SHA256
        detector = SmartTurnCPU(args.model)
        if "torch" in sys.modules:
            raise RuntimeError("turn_end_worker_imported_torch")
        if args.probe_model:
            started = time.perf_counter()
            probability = detector.predict(b"\x00\x00" * 16000)
            print(json.dumps({"version": 1, "status": "ok", "model_sha256": MODEL_SHA256,
                              "probability": probability, "provider": detector.session.get_providers(),
                              "input_shape": detector.session.get_inputs()[0].shape,
                              "feature_shape": [1, 80, 800], "torch_imported": "torch" in sys.modules,
                              "processing_ms": round((time.perf_counter() - started) * 1000, 3)}))
            return 0
    except Exception:
        _reply(sys.stdout.buffer, {"version": 1, "status": "unavailable", "reason": "model_or_runtime_unavailable"})
        return 2
    if not args.worker:
        parser.error("select --worker or --probe-model")
    return worker_loop(detector, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
