"""既有BGE快照的CPU配对实验。默认仅读元数据，执行需主会话CPU调度收据。"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import struct
import subprocess
import sys
from time import perf_counter, sleep
import uuid

from .adapters import bge_candidate_identity, bge_cpu_int8_candidate
from .benchmark import ranking_gate

ROOT = Path(__file__).resolve().parents[4]
REVISION = "7999e1d3359715c523056ef9478215996d62a620"
DOCUMENTS = (
    "工作日早上八点先吃早餐，再开始处理工作。",
    "周末早上九点吃早餐，下午去公园散步。",
    "星期二下午三点开项目会议，需要提前检查麦克风。",
    "星期三下午四点整理会议纪要，并发送给项目成员。",
    "室内薄荷每周浇水两次，土壤干了再补水。",
    "仙人掌每月少量浇水一次，避免花盆积水。",
    "测试服务器地址使用localhost，Python版本固定为3.12。",
    "网页开发使用Node.js和pnpm，先运行本地单元测试。",
    "喜欢喝温热的乌龙茶，不喜欢在晚上喝咖啡。",
    "午饭后可以喝一杯咖啡，晚上改喝温水。",
    "出门前确认钥匙、手机和雨伞已经放进背包。",
    "旅行结束后先整理行李，再备份相机里的照片。",
)
QUERIES = (
    ("weekday-breakfast", "工作日几点吃早餐？", {0}),
    ("meeting-time", "星期二的项目会议安排在几点？", {2}),
    ("plant-water", "仙人掌多久浇一次水？", {5}),
    ("python-loopback", "本地测试服务器的地址和Python版本是什么？", {6}),
)


def metadata_plan(model: Path) -> dict:
    """只读safetensors头/配置/文件大小，不读取权重载荷、不导入torch。"""
    config = json.loads((model / "config.json").read_text(encoding="utf-8"))
    weight = model / "model.safetensors"
    with weight.open("rb") as stream:
        size = struct.unpack("<Q", stream.read(8))[0]
        if not 2 <= size <= 1024 * 1024:
            raise ValueError("unexpected_safetensors_header_size")
        header = json.loads(stream.read(size))
    tensors = {name: value for name, value in header.items() if name != "__metadata__"}
    payload = sum(value["data_offsets"][1] - value["data_offsets"][0] for value in tensors.values())
    linear = sum(value["data_offsets"][1] - value["data_offsets"][0] for name, value in tensors.items()
                 if name.endswith(".weight") and len(value["shape"]) == 2 and "embeddings." not in name)
    candidate = payload - linear + linear // 4
    return dict(schema_version=1, stage="metadata_only_no_model_load", model_revision=REVISION,
                model_type=config["model_type"], layers=config["num_hidden_layers"], hidden_size=config["hidden_size"],
                weight_file_bytes=weight.stat().st_size, fp32_payload_mib=payload / 2**20,
                linear_fp32_mib=linear / 2**20, estimated_int8_payload_mib=candidate / 2**20,
                estimated_out_of_place_weight_peak_mib=(2 * payload + candidate) / 2**20,
                estimate_excludes="runtime_imports_allocator_packed_weights_and_activations",
                process_memory_estimate_mib=[600, 1200], process_memory_limit_mib=2048,
                max_seconds=180, torch_threads=2, interop_threads=1,
                documents=len(DOCUMENTS), queries=len(QUERIES), repeats=3, batch_sizes=[1, 8],
                maximum_forward_calls=40, time_estimate_seconds=[60, 180], estimates_measured=False,
                model_load_executed=False, production_ready=False)


def _owned_encoder_class():
    sys.path.insert(0, str(ROOT / "src"))
    from longmemory.adapters.llm import local_embedding
    if Path(local_embedding.__file__).resolve() != ROOT / "src/longmemory/adapters/llm/local_embedding.py":
        raise RuntimeError("encoder_source_not_owned_worktree")
    return local_embedding.LocalBGEEncoder


def _scores(query, docs):
    return [sum(a * b for a, b in zip(query, doc)) for doc in docs]


def run_loaded(encoder, torch, *, clock=perf_counter, expected_dimensions=512) -> dict:
    """已调度worker内部调用；只替换自己的encoder实例，不触碰共享服务。"""
    original = encoder._model
    quant_started = clock()
    candidate = bge_cpu_int8_candidate(original, torch=torch)
    quant_ms = (clock() - quant_started) * 1000
    if not candidate.applied:
        raise RuntimeError(candidate.reason)
    models = {"fp32": original, "int8": candidate.candidate}
    docs = {}
    query_vectors = {name: {} for name in models}
    records = []
    edge = {}
    hooks = []
    forward_counts = {name: 0 for name in models}
    def count_for(name):
        def count(_model, _inputs):
            forward_counts[name] += 1
            if sum(forward_counts.values()) > 40:
                raise RuntimeError("forward_call_budget_exceeded")
        return count
    for name, model in models.items():
        if hasattr(model, "register_forward_pre_hook"):
            hooks.append(model.register_forward_pre_hook(count_for(name)))
    def validate(vectors):
        for vector in vectors:
            if len(vector) != expected_dimensions or not all(math.isfinite(x) for x in vector):
                raise RuntimeError("embedding_dimensions_or_finiteness_changed")
            if abs(math.sqrt(sum(x*x for x in vector)) - 1) > 1e-5:
                raise RuntimeError("embedding_l2_normalization_changed")
        return vectors
    try:
        for name, model in models.items():
            encoder._model = model
            encoder.encode_query(QUERIES[0][1])
            docs[name] = validate(encoder.encode_documents(DOCUMENTS))
        for repeat in range(3):
            order = ("fp32", "int8") if repeat % 2 == 0 else ("int8", "fp32")
            for case_id, text, _labels in QUERIES:
                for name in order:
                    encoder._model = models[name]
                    began = clock()
                    vector = encoder.encode_query(text)
                    records.append(dict(engine=name, case_id=case_id, repeat=repeat, batch_size=1,
                                        elapsed_ms=(clock() - began) * 1000))
                    validate([vector])
                    query_vectors[name][case_id] = vector
            for name in order:
                encoder._model = models[name]
                began = clock()
                encoder.encode_documents(DOCUMENTS[:8])
                records.append(dict(engine=name, case_id="documents-batch8", repeat=repeat, batch_size=8,
                                    elapsed_ms=(clock() - began) * 1000))
        for name, model in models.items():
            encoder._model = model
            # 中文单字逐token，保留真实tokenizer及原512窗口拒绝语义。
            exact = "中" * 510
            token_count = len(encoder._tokenizer(exact)["input_ids"])
            if token_count != 512:
                raise RuntimeError("boundary_fixture_tokenizer_mismatch")
            vectors = validate(encoder.encode_documents([exact]))
            edge[name] = dict(exact_512_finite=all(math.isfinite(x) for x in vectors[0]))
            for key, action in (
                ("overlength_rejected", lambda: encoder.encode_documents(["中" * 511])),
                ("empty_query_rejected", lambda: encoder.encode_query("")),
                ("empty_document_rejected", lambda: encoder.encode_documents([""])),
            ):
                try:
                    action()
                    edge[name][key] = False
                except ValueError:
                    edge[name][key] = True
        baseline_scores, same_index_scores, rebuilt_scores, labels = [], [], [], []
        for case_id, _text, relevant in QUERIES:
            baseline_scores.append(_scores(query_vectors["fp32"][case_id], docs["fp32"]))
            same_index_scores.append(_scores(query_vectors["int8"][case_id], docs["fp32"]))
            rebuilt_scores.append(_scores(query_vectors["int8"][case_id], docs["int8"]))
            labels.append(relevant)
        gates = {
            "existing_fp32_synthetic_index": ranking_gate(baseline_scores, same_index_scores, labels, k=3),
            "rebuilt_int8_synthetic_index": ranking_gate(baseline_scores, rebuilt_scores, labels, k=3),
        }
        timings = {}
        for batch in (1, 8):
            pair = {name: statistics.median(row["elapsed_ms"] for row in records
                                           if row["engine"] == name and row["batch_size"] == batch) for name in models}
            timings[str(batch)] = dict(pair, fp32_over_int8_ratio=pair["fp32"] / pair["int8"] if pair["int8"] else None)
        return dict(stage="isolated_cpu_measured", quantization_ms=quant_ms, timings_median_ms=timings,
                    records=records, ranking_gates=gates, boundary_checks=edge,
                    dimensions=expected_dimensions, l2_normalization_verified=True, forward_counts=forward_counts,
                    all_automatic_gates_passed=all(g["automatic_passed"] for g in gates.values()) and all(all(v.values()) for v in edge.values()),
                    final_memory_answers_verified=False, production_ready=False)
    finally:
        encoder._model = original
        for hook in hooks:
            hook.remove()


def worker(model: Path, output: Path, window_id: str, start_gate: Path):
    if not window_id.strip():
        raise ValueError("cpu_window_receipt_required")
    gate_began = perf_counter()
    while not start_gate.is_file():
        if perf_counter() - gate_began > 10:
            raise RuntimeError("resource_job_start_gate_timeout")
        sleep(0.05)
    if start_gate.read_text(encoding="utf-8") != window_id:
        raise RuntimeError("resource_job_start_gate_mismatch")
    import socket
    def denied(*_args, **_kwargs):
        raise RuntimeError("bge_benchmark_network_forbidden")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.socket.sendto = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    encoder_type = _owned_encoder_class()
    began = perf_counter()
    encoder = encoder_type(model)
    load_ms = (perf_counter() - began) * 1000
    identity_before = encoder.identity
    baseline_model = encoder._model
    result = run_loaded(encoder, torch)
    identities = bge_candidate_identity(encoder.metadata)
    if identities["baseline_identity"] != identity_before:
        raise RuntimeError("baseline_identity_contract_changed")
    result.update(model_load_ms=load_ms, model_identity=identity_before, model_metadata=encoder.metadata,
                  source_origin=str(ROOT / "src/longmemory/adapters/llm/local_embedding.py"),
                  source_sha256=hashlib.sha256((ROOT / "src/longmemory/adapters/llm/local_embedding.py").read_bytes()).hexdigest(),
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  adapter_sha256=hashlib.sha256(Path(__file__).with_name("adapters.py").read_bytes()).hexdigest(),
                  baseline_instance_restored=encoder._model is baseline_model,
                  torch_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                  cpu_window_id=window_id, synthetic_corpus_only=True)
    result.update(identities)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)


class WindowsResourceJob:
    """Job Object硬性限单进程提交内存与两CPU；关闭时只结束本Job所属进程。"""
    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.Extended = Extended
        self.kernel = kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
        if not kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ctypes.byref(process_mask), ctypes.byref(system_mask)):
            raise OSError("cannot_get_owned_affinity_mask")
        bits = [1 << index for index in range(ctypes.sizeof(ctypes.c_size_t)*8) if process_mask.value & (1 << index)]
        if not bits:
            raise OSError("empty_owned_affinity_mask")
        self.affinity = sum(bits[:2])
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("cannot_create_owned_resource_job")
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x100 | 0x200 | 0x2000 | 0x10
        limits.BasicLimitInformation.Affinity = self.affinity
        limits.ProcessMemoryLimit = 2048 * 2**20
        limits.JobMemoryLimit = 2048 * 2**20
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError("cannot_set_owned_resource_job_limits")
    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            raise OSError("cannot_assign_owned_worker_to_resource_job")
    def snapshot(self):
        limits = self.Extended()
        if not self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None):
            raise OSError("cannot_query_owned_resource_job")
        return dict(peak_job_memory_bytes=limits.PeakJobMemoryUsed,
                    process_memory_limit_bytes=limits.ProcessMemoryLimit,
                    job_memory_limit_bytes=limits.JobMemoryLimit,
                    affinity_mask=limits.BasicLimitInformation.Affinity)
    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        self.close()


def execute_owned(model: Path, window_id: str) -> dict:
    if not window_id.strip() or sys.platform != "win32":
        raise ValueError("windows_cpu_window_receipt_required")
    output = ROOT / "experiments/runs" / ("ag-bge-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from acceleration.bge_benchmark import worker; worker(Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4],Path(sys.argv[5]))"
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
               TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", CUDA_VISIBLE_DEVICES="")
    started = perf_counter()
    peak = 0
    stop_reason = None
    job = WindowsResourceJob()
    start_gate = output / "resource-job-ready"
    with job, (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(Path(__file__).parent.parent),
                                    str(model.resolve()), str(output / "report.json"), window_id, str(start_gate)],
                                   cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        try:
            job.assign(process)
            with start_gate.open("x", encoding="utf-8") as handle:
                handle.write(window_id)
            while process.poll() is None:
                if perf_counter() - started > 180:
                    stop_reason = "owned_worker_wall_budget_exceeded"
                    break
                try:
                    peak = max(peak, job.snapshot()["peak_job_memory_bytes"])
                except OSError:
                    if process.poll() is None:
                        stop_reason = "owned_worker_memory_guard_unavailable"
                        break
                if peak > 2048 * 2**20:
                    stop_reason = "owned_worker_memory_budget_exceeded"
                    break
                sleep(0.1)
        finally:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                try:
                    peak = max(peak, job.snapshot()["peak_job_memory_bytes"])
                except OSError:
                    stop_reason = stop_reason or "owned_worker_final_memory_query_unavailable"
            finally:
                job.close()
    receipt = dict(exit_code=process.returncode, stop_reason=stop_reason, peak_job_memory_mib=peak / 2**20,
                   wall_seconds=perf_counter() - started, output=str(output), cpu_window_id=window_id,
                   scope="only_spawned_worker; no_services_or_index_changes", production_ready=False)
    receipt.update(job_process_memory_limit_mib=2048, affinity_mask=job.affinity,
                   cpu_affinity_logical_count=job.affinity.bit_count(), resource_job_enforced=True)
    with (output / "receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--cpu-window-id", default="")
    args = parser.parse_args()
    result = execute_owned(args.model, args.cpu_window_id) if args.execute else metadata_plan(args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
