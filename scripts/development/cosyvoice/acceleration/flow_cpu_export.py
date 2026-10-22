"""真实CosyVoice3 Flow的受限CPU导出入口；不启动声音服务或CUDA。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .bge_benchmark import WindowsResourceJob
from .capabilities import sha256, verify_source

ROOT = Path(__file__).resolve().parents[4]


def worker(payload):
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError("CPU_flow_export_no_network_or_cuda")
    socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = denied
    socket.getaddrinfo = socket.create_connection = denied
    import numpy as np
    import torch
    torch.cuda._lazy_init = torch.cuda.init = denied
    if torch.__version__ != "2.3.1+cu121":
        raise RuntimeError("fixed_torch_2_3_1_required")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    source, model, output = (Path(payload[name]) for name in ("source", "model", "output"))
    if not verify_source(source)["verified"]:
        raise RuntimeError("fixed_cosy_source_mismatch")
    from .flow_trtexec import PINNED, NAMES, shapes
    if sha256(model/"flow.pt") != PINNED["flow.pt"]:
        raise RuntimeError("flow_weights_mismatch")
    sys.path.insert(0, str(source))
    from cosyvoice.flow.DiT.dit import DiT
    print("Loading real Flow weights on CPU", flush=True)
    estimator = DiT(dim=1024, depth=22, heads=16, dim_head=64, ff_mult=2, mel_dim=80,
                    mu_dim=80, spk_dim=80, out_channels=80, static_chunk_size=50, num_decoding_left_chunks=-1)
    checkpoint = torch.load(model/"flow.pt", map_location="cpu", weights_only=True, mmap=True)
    state = {name.removeprefix("decoder.estimator."): value for name, value in checkpoint.items() if name.startswith("decoder.estimator.")}
    estimator.load_state_dict(state, strict=True, assign=True)
    del state, checkpoint
    estimator = estimator.eval().float()
    streaming = payload["mode"] == "incremental"
    class Flow(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner
        def forward(self, x, mask, mu, t, spks, cond):
            return self.inner(x, mask, mu, t, spks, cond, streaming=streaming)
    module = Flow(estimator).eval()
    rng = np.random.default_rng(1828)
    values = {name:rng.standard_normal(shape, dtype=np.float32) for name, shape in shapes(128).items()}
    values["mask"].fill(1)
    for name in ("mu", "spks", "cond"):
        values[name][1] = 0
    example = tuple(torch.from_numpy(values[name]) for name in NAMES)
    print("Exporting real Flow "+payload["mode"]+" graph and external FP32 weights", flush=True)
    from .external_weights import export_module
    from torch.nn.attention import SDPBackend, sdpa_kernel
    # ONNX把SDPA展开为math；参考也用math，不能混入CPU flash的另一条FP32归约路径。
    with torch.no_grad(), sdpa_kernel(SDPBackend.MATH):
        bundle = export_module(module, example, output/"external-candidate", input_names=NAMES,
                               output_names=("estimator_out",), opset=18,
                               dynamic_axes={name:{2:"seq_len"} for name in ("x", "mask", "mu", "cond", "estimator_out")})
        expected = module(*example).numpy()
    case = output/"n128-full"
    case.mkdir()
    for name in NAMES:
        values[name].tofile(case/(name+".bin"))
    expected.tofile(case/"expected.bin")
    result = dict(status="cpu_onnx_exported", mode=payload["mode"], streaming=streaming,
                  source_commit=verify_source(source)["source_commit"], flow_sha256=PINNED["flow.pt"],
                  bundle=bundle, reference_case="n128-full", precision="fp32")
    (output/"export.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("ONNX ready: "+str(output/"external-candidate/package/model.onnx"), flush=True)


def execute(source, model, output, mode):
    began = perf_counter()
    output = output.resolve()
    if output.exists() or ROOT/"experiments/runs" not in output.parents:
        raise ValueError("fresh_output_in_assigned_worktree_required")
    output.mkdir(parents=True)
    payload = dict(source=str(source.resolve()), model=str(model.resolve()), output=str(output), mode=mode)
    code = "import sys,json;sys.path.insert(0,sys.argv[1]);from acceleration.flow_cpu_export import worker;worker(json.load(sys.stdin))"
    argv = [str(source/".venv/Scripts/python.exe"), "-I", "-B", "-c", code, str(Path(__file__).parent.parent)]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", TMP=str(output), TEMP=str(output))
    result = dict(status="failed", mode=mode)
    with WindowsResourceJob(memory_limit_mib=6144, logical_cpus=2) as job, (output/"export.log").open("xb") as log:
        process = None
        try:
            process = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
            job.assign(process)
            process.communicate(json.dumps(payload).encode(), timeout=max(1,240-(perf_counter()-began)))
            if process.returncode:
                raise RuntimeError("CPU_flow_export_failed; see export.log")
            result["status"] = "cpu_onnx_exported"
        finally:
            result.update(seconds=perf_counter()-began, resources=job.snapshot())
            result["owned_tree_exit_confirmed"] = job.terminate_and_confirm()
            if process is not None:
                process.wait(timeout=5)
                result["exit_code"] = process.returncode
            result["active_after"] = job.snapshot()["active_processes"]
            (output/"cpu-export.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "model", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--mode", choices=("incremental", "buffered"), default="incremental")
    args = parser.parse_args()
    print(json.dumps(execute(args.source, args.model, args.output, args.mode)))


if __name__ == "__main__":
    main()
