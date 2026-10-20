"""现有SDK11 C++工具的独立FP32 flow实验。默认仅计划；执行须新GPU窗口。

不调用AutoModel、不载入LLM/HiFT/声线，不安装Python TRT绑定，不改AD服务。
首轮仅buffered图、batch2、16..512帧；engine不直接接torch cu121指针。
"""

from __future__ import annotations

import argparse
import json
import os
import pickletools
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from time import perf_counter, sleep

from .capabilities import sha256, verify_source
from .bge_benchmark import WindowsResourceJob

ROOT = Path(__file__).resolve().parents[4]
NAMES = ("x", "mask", "mu", "t", "spks", "cond")
LENGTHS = (16, 127, 128, 257, 512)
PINNED = {
    "flow.pt": "a6fab32a7825e5b0bc855ddd948f8db9370b0a786fbc249caa4595e95b608e4b",
    "cosyvoice3.yaml": "f5a6b2c6f05139d0f18861a1fe506f751e787026b77c05f7e8fef9f8a4405965",
    "cosyvoice/flow/DiT/dit.py": "5d14492e3ed68f5446853b0defd447bc401b12803b027a7b9584a3f3527633bf",
    "cosyvoice/flow/DiT/modules.py": "8c97f2af995e9ce06288be35b5119b243bb6a1aec687ef23032f20314f3f18cf",
    "cosyvoice/utils/mask.py": "852c6e4b14201a238ab076396db599c157b2ee5a5a2aacf0f277ddce8c648976",
    "bin/trtexec.exe": "0b7f547a086b191d95424ac2739f8fe9a61a6b39a0ca4cb0d3dfbbf643796913",
    "bin/nvinfer_11.dll": "19a836028d37b9dfe3171b88678c7c3b5abdba94ac79bee81c3be963569c5cd3",
    "bin/nvonnxparser_11.dll": "9d15046ade1740a0f53d2d707e632de6b44525a6a5e02d1e78c5b39bb7b1000c",
    "bin/nvinfer_builder_resource_sm89_11.dll": "f40b200da982599e8ddbfb372c8ca7788f6c16518d952492f7264d2037cbce1b",
    "python/tensorrt-11.2.1.2-cp310-none-win_amd64.whl": "f7f5174f416075c8101352e9afe04b991c50a87ce024fb26af41dd95ffb0c097",
}


def shapes(length):
    if not 16 <= length <= 512:
        raise ValueError("outside_validated_profile_keep_eager")
    return dict(x=(2, 80, length), mask=(2, 1, length), mu=(2, 80, length),
                t=(2,), spks=(2, 80), cond=(2, 80, length))


def shape_arg(length):
    return ",".join(name + ":" + "x".join(map(str, shape)) for name, shape in shapes(length).items())


def case_id(length, padded):
    return f"n{length}-{'padded' if padded else 'full'}"


def build_command(sdk: Path, output: Path):
    return [str(sdk / "bin/trtexec.exe"), "--onnx=" + str(output / "flow.fp32.onnx"),
            "--saveEngine=" + str(output / "flow.fp32.plan"), "--minShapes=" + shape_arg(16),
            "--optShapes=" + shape_arg(128), "--maxShapes=" + shape_arg(512),
            "--noTF32", "--builderOptimizationLevel=0", "--maxTactics=8", "--memPoolSize=workspace:512M",
            "--noCompilationCache", "--skipInference", "--profilingVerbosity=detailed",
            "--exportLayerInfo=" + str(output / "engine-layers.json")]


def run_command(sdk: Path, output: Path, length: int, padded: bool):
    case = output / case_id(length, padded)
    # TensorRT原生参数解析要求给Windows盘符路径引用input名；不经过shell。
    inputs = ",".join("'" + name + "':" + str(case / (name + ".bin")) for name in NAMES)
    return [str(sdk / "bin/trtexec.exe"), "--loadEngine=" + str(output / "flow.fp32.plan"),
            "--shapes=" + shape_arg(length), "--loadInputs=" + inputs,
            "--iterations=1", "--duration=0", "--warmUp=0", "--infStreams=1", "--avgRuns=1",
            "--includeDataTransfers", "--noCudaGraph", "--noSpinWait",
            "--exportOutput=" + str(case / "trt-output.json"), "--exportTimes=" + str(case / "trt-times.json")]


def resource_plan(source: Path, model: Path, sdk: Path, toolkit: Path, output: Path):
    files = {}
    for name, expected in PINNED.items():
        base = model if name in ("flow.pt", "cosyvoice3.yaml") else source if name.startswith("cosyvoice/") else sdk
        target = base / name
        actual = sha256(target) if target.is_file() else None
        files[name] = dict(bytes=target.stat().st_size if target.is_file() else None, sha256=actual, matches=actual == expected)
    cudart = toolkit / "bin/x64/cudart64_13.dll"
    files["cudart64_13.dll"] = dict(sha256=sha256(cudart) if cudart.is_file() else None,
                                     matches=cudart.is_file() and sha256(cudart) == "b00ca6f53699120da815bf3e06e2e4285fae2f201235b883dcbb50eec51e2a2a")
    with zipfile.ZipFile(model / "flow.pt") as archive:
        entry = next(name for name in archive.namelist() if name.endswith("/data.pkl"))
        if archive.getinfo(entry).file_size > 16*2**20:
            raise ValueError("checkpoint_metadata_too_large")
        metadata = archive.read(entry)
    estimator_keys = [arg for op, arg, _ in pickletools.genops(metadata)
                      if op.name in ("BINUNICODE", "SHORT_BINUNICODE", "UNICODE") and isinstance(arg, str) and arg.startswith("decoder.estimator.")]
    executable_bytes = (sdk / "bin/trtexec.exe").read_bytes()
    cli_flags = {flag: flag.encode("ascii") in executable_bytes for flag in (
        "--noTF32", "--maxTactics", "--memPoolSize", "--skipInference", "--exportOutput",
        "--noCudaGraph", "--includeDataTransfers", "--noSpinWait", "--noCompilationCache")}
    return dict(status="needs_isolated_validation", resources_match=all(x["matches"] for x in files.values()) and all(cli_flags.values()) and verify_source(source)["verified"] and len(estimator_keys) == 323,
                files=files, source_verified=verify_source(source)["verified"], downloads_required=False,
                harness_sha256=sha256(Path(__file__)), job_harness_sha256=sha256(Path(__file__).with_name("bge_benchmark.py")),
                native_cli_flag_strings=cli_flags,
                checkpoint_metadata=dict(bytes=len(metadata), estimator_keys=len(estimator_keys), unpickled=False, weights_loaded=False),
                output=str(output), builder_argv=build_command(sdk, output), sample_runner_argv=run_command(sdk, output, 127, True),
                matrix=dict(lengths=LENGTHS, masks=["full", "last_quarter_zero"], streaming=False, batch=2, dtype="float32", cases=10),
                bounds=dict(export_seconds=240, build_seconds=600, each_run_seconds=45, whole_seconds=1320,
                            host_job_memory_mib=6144, cpu_logical_count=2, workspace_mib=512,
                            disk_limit_gib=6, disk_free_required_gib=8, gpu_observed_used_limit_mib=12288,
                            torch_allocator_limit_mib=6144, gpu_free_required_mib=8192),
                estimates=dict(export_seconds=[60, 240], build_seconds=[120, 600], total_minutes=[5, 22],
                               host_peak_gib=[3, 6], gpu_peak_gib=[2, 6], artifacts_gib=[3, 6], measured=False),
                caveats=["workspace_is_not_total_vram_cap", "nvidia_smi_watchdog_is_sampling_not_hard_vram_limit",
                         "no_service_integration_or_audio_quality_claim", "abort_only_terminates_owned_offline_job"])


def export_worker(source: Path, model: Path, output: Path, gate: Path, window_id: str):
    if not window_id:
        raise ValueError("gpu_window_receipt_required")
    began = perf_counter()
    while not gate.is_file():
        if perf_counter() - began > 10:
            raise RuntimeError("resource_job_gate_timeout")
        sleep(.05)
    if gate.read_text(encoding="utf-8") != window_id:
        raise ValueError("resource_job_gate_mismatch")
    import socket
    def denied(*_args, **_kwargs):
        raise RuntimeError("offline_export_network_forbidden")
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = denied
    socket.getaddrinfo = socket.create_connection = denied
    import numpy as np
    import torch
    import onnx
    import onnxruntime as ort
    from importlib.metadata import version
    if torch.__version__ != "2.3.1+cu121":
        raise RuntimeError("fixed_cosy_torch_required")
    if (np.__version__, onnx.__version__, ort.__version__, version("transformers"), version("x-transformers")) != ("1.26.4", "1.16.0", "1.18.0", "4.51.3", "2.11.24"):
        raise RuntimeError("fixed_cosy_export_dependencies_required")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(6144 / (torch.cuda.get_device_properties(0).total_memory / 2**20), 0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    sys.path.insert(0, str(source))
    from cosyvoice.flow.DiT.dit import DiT
    import inspect
    if Path(inspect.getfile(DiT)).resolve() != (source / "cosyvoice/flow/DiT/dit.py").resolve():
        raise RuntimeError("dit_import_source_mismatch")
    # 固定配置逐项核对；不执行包含cuda.manual_seed_all/LLM/HiFT构造的hyperpyyaml。
    estimator = DiT(dim=1024, depth=22, heads=16, dim_head=64, ff_mult=2, mel_dim=80,
                    mu_dim=80, spk_dim=80, out_channels=80, static_chunk_size=50, num_decoding_left_chunks=-1)
    checkpoint = torch.load(model / "flow.pt", map_location="cpu", weights_only=True, mmap=True)
    state = {key.removeprefix("decoder.estimator."): value for key, value in checkpoint.items() if key.startswith("decoder.estimator.")}
    if not state:
        raise RuntimeError("estimator_checkpoint_prefix_missing")
    estimator.load_state_dict(state, strict=True, assign=True)
    del checkpoint, state
    estimator = estimator.eval().float().to("cuda")
    class Buffered(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner
        def forward(self, x, mask, mu, t, spks, cond):
            return self.inner(x, mask, mu, t, spks, cond, streaming=False)
    module = Buffered(estimator).eval()
    def inputs(length, padded):
        rng = np.random.default_rng(1700 + length)
        values = {name: rng.standard_normal(shape, dtype=np.float32) for name, shape in shapes(length).items()}
        values["mask"].fill(1)
        if padded:
            values["mask"][:, :, length*3//4:] = 0
        for name in ("mu", "spks", "cond"):
            values[name][1] = 0  # 与固定上游CFG（无条件分支）输入布局一致。
        return values
    example = inputs(128, False)
    with torch.no_grad(), torch.backends.cuda.sdp_kernel(enable_flash=False, enable_math=True, enable_mem_efficient=False):
        torch.onnx.export(module, tuple(torch.from_numpy(example[name]).cuda() for name in NAMES), str(output / "flow.fp32.onnx"),
                          input_names=list(NAMES), output_names=["estimator_out"], export_params=True,
                          opset_version=18, do_constant_folding=True,
                          dynamic_axes={name: {2: "seq_len"} for name in ("x", "mask", "mu", "cond", "estimator_out")})
        onnx.checker.check_model(str(output / "flow.fp32.onnx"))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(output / "flow.fp32.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        io = session.get_inputs()
        if [item.name for item in io] != list(NAMES) or any(item.type != "tensor(float)" for item in io):
            raise RuntimeError("exported_input_names_or_dtypes_changed")
        for item in io:
            expected_shape = list(shapes(128)[item.name])
            if item.name in ("x", "mask", "mu", "cond"):
                expected_shape[-1] = "seq_len"
            if item.shape != expected_shape:
                raise RuntimeError("exported_dynamic_shape_contract_changed")
        outputs = session.get_outputs()
        if len(outputs) != 1 or outputs[0].name != "estimator_out" or outputs[0].type != "tensor(float)" or outputs[0].shape != [2, 80, "seq_len"]:
            raise RuntimeError("exported_output_contract_changed")
        checks = []
        for length in LENGTHS:
            for padded in (False, True):
                values = inputs(length, padded)
                expected = module(*(torch.from_numpy(values[name]).cuda() for name in NAMES)).cpu().numpy()
                actual = session.run(["estimator_out"], values)[0]
                np.testing.assert_allclose(actual, expected, rtol=1e-2, atol=1e-4)
                case = output / case_id(length, padded)
                case.mkdir()
                for name in NAMES:
                    values[name].tofile(case / (name + ".bin"))
                expected.tofile(case / "expected.bin")
                checks.append(dict(case=case.name, shape=list(expected.shape), ort_eager_allclose=True))
    receipt = dict(onnx_sha256=sha256(output / "flow.fp32.onnx"), checks=checks, streaming=False,
                   numpy=np.__version__, onnx=onnx.__version__, ort=ort.__version__, torch=torch.__version__,
                   gpu=torch.cuda.get_device_name(0), torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
                   torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20, cpu_window_id=None, gpu_window_id=window_id)
    with (output / "export-receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)


def compare_output(output: Path, length: int, padded: bool):
    import numpy as np
    case = output / case_id(length, padded)
    rows = json.loads((case / "trt-output.json").read_text(encoding="utf-8"))
    if len(rows) != 1 or rows[0]["name"] != "estimator_out":
        raise ValueError("trt_output_binding_changed")
    expected = np.fromfile(case / "expected.bin", dtype="<f4")
    actual = np.asarray(rows[0]["values"], dtype=np.float32)
    if list(map(int, re.findall(r"\d+", rows[0].get("dimensions", "")))) != [2, 80, length]:
        raise ValueError("trt_output_dimensions_changed")
    if actual.size != 2*80*length or expected.size != actual.size or not np.isfinite(actual).all():
        raise ValueError("trt_output_shape_or_values_invalid")
    np.testing.assert_allclose(actual, expected, rtol=1e-2, atol=1e-4)
    return dict(case=case.name, allclose=True, max_abs_error=float(np.max(np.abs(actual-expected))))


def gpu_memory():
    done = subprocess.run(["nvidia-smi", "--id=0", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, timeout=5, check=True)
    used, free = map(int, done.stdout.strip().split(","))
    return used, free


def bounded(command, output: Path, label: str, env: dict, seconds: int, *, gate=None, window_id="", whole_deadline=None):
    started = perf_counter()
    if not window_id.strip():
        raise ValueError("gpu_window_receipt_required")
    if gate is None:
        gate = output / (label + ".job-ready")
        # 原生程序也先由轻量broker等待Job配置完成，其后代继承内存/亲和性限制。
        broker = "import json,sys,time,subprocess; from pathlib import Path; p=Path(sys.argv[1]); end=time.monotonic()+10;\nwhile not p.is_file():\n if time.monotonic()>end: raise RuntimeError('job_gate_timeout')\n time.sleep(.05)\nif p.read_text(encoding='utf-8')!=sys.argv[3]: raise RuntimeError('job_gate_mismatch')\nsys.exit(subprocess.call(json.loads(sys.argv[2])))"
        command = [sys.executable, "-I", "-B", "-c", broker, str(gate), json.dumps(command), window_id]
    with WindowsResourceJob(memory_limit_mib=6144) as job, (output / (label+".log")).open("xb") as log:
        process = subprocess.Popen(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            job.assign(process)
            if gate is not None:
                with gate.open("x", encoding="utf-8") as stream:
                    stream.write(window_id)
            while process.poll() is None:
                if perf_counter()-started > seconds or (whole_deadline is not None and perf_counter() > whole_deadline):
                    raise TimeoutError("owned_stage_wall_budget_exceeded")
                if sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) > 6*2**30:
                    raise RuntimeError("owned_stage_disk_budget_exceeded")
                if gpu_memory()[0] > 12288:
                    raise RuntimeError("observed_device_vram_budget_exceeded")
                sleep(.5)
            if process.returncode:
                raise RuntimeError("owned_stage_failed:" + label)
            return dict(stage=label, exit_code=0, seconds=perf_counter()-started, **job.snapshot())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def execute(source: Path, model: Path, sdk: Path, toolkit: Path, output: Path, python: Path, window_id: str):
    output = output.resolve()
    if not window_id.strip() or sys.platform != "win32":
        raise ValueError("new_exclusive_gpu_window_required")
    if output.exists() or ROOT / "experiments/runs" not in output.parents or source.resolve() in output.parents:
        raise ValueError("new_owned_experiment_output_required")
    plan = resource_plan(source, model, sdk, toolkit, output)
    if not plan["resources_match"] or shutil.disk_usage(ROOT).free < 8*2**30 or gpu_memory()[1] < 8192:
        raise RuntimeError("resources_or_free_capacity_not_ready")
    output.mkdir(parents=True)
    for name in ("tmp", "cuda-cache"):
        (output / name).mkdir()
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_CACHE_PATH=str(output / "cuda-cache"),
               TMP=str(output / "tmp"), TEMP=str(output / "tmp"), OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    stages = []
    deadline = perf_counter() + 1320
    try:
        identity = subprocess.run(["nvidia-smi", "--id=0", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                                  capture_output=True, text=True, timeout=5, check=True)
        plan["gpu_metadata_at_window"] = identity.stdout.strip()
        with (output / "plan.json").open("x", encoding="utf-8") as handle:
            json.dump(plan, handle, indent=2)
        gate = output / "export-job-ready"
        code = "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from acceleration.flow_trtexec import export_worker; export_worker(*(Path(x) for x in sys.argv[2:6]),sys.argv[6])"
        command = [str(python), "-I", "-B", "-c", code, str(Path(__file__).parent.parent), str(source), str(model), str(output), str(gate), window_id]
        stages.append(bounded(command, output, "export", env, 240, gate=gate, window_id=window_id, whole_deadline=deadline))
        native_env = dict(env, PATH=os.pathsep.join(map(str, (sdk/"bin", toolkit/"bin/x64", toolkit/"bin", Path(os.environ["SystemRoot"])/"System32"))))
        stages.append(bounded(build_command(sdk, output), output, "build", native_env, 600, window_id=window_id, whole_deadline=deadline))
        checks = []
        for length in LENGTHS:
            for padded in (False, True):
                stages.append(bounded(run_command(sdk, output, length, padded), output, case_id(length, padded), native_env, 45, window_id=window_id, whole_deadline=deadline))
                checks.append(compare_output(output, length, padded))
        result = dict(status="offline_flow_numeric_candidate_only", stages=stages, checks=checks,
                      plan_sha256=sha256(output/"flow.fp32.plan"), production_ready=False, audio_quality_verified=False,
                      interruption_verified=False, dynamic_profile_max=512, gpu_window_id=window_id)
    except Exception as error:
        result = dict(status="failed_stop_no_retry", error=type(error).__name__, reason=str(error), stages=stages, gpu_window_id=window_id)
        with (output / "result.json").open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        raise
    with (output / "result.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "model", "sdk", "toolkit", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--gpu-window-id", default="")
    args = parser.parse_args()
    if args.execute and args.python is None:
        parser.error("--execute requires explicit fixed Cosy --python")
    values = {name: getattr(args, name).resolve() for name in ("source", "model", "sdk", "toolkit", "output")}
    result = execute(**values, python=args.python or Path(sys.executable), window_id=args.gpu_window_id) if args.execute else resource_plan(**values)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
