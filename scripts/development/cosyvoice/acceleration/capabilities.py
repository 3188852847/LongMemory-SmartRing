"""只读检查固定源码及当前解释器元数据；没有安装、模型加载或联网行为。"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

SOURCE_COMMIT = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
SOURCE_HASHES = {
    "cosyvoice/cli/cosyvoice.py": "4b2a605f129d172cd031286a14a591396c2e8ed0bf53258acc7445525fdaa65b",
    "cosyvoice/cli/model.py": "421ba52dd956505667668e0aec7fdcbcd85d733b52725b2d595bc32bcbb53ef9",
    "cosyvoice/utils/file_utils.py": "aeb9792d4a828f51e42339139cc97753ea931ab246df2f5f5d2703043fb5db72",
    "cosyvoice/utils/common.py": "69aab9fe9cc80173f72a608e1b632611174f8c8e5032e4d9ce24fef18c8574bd",
    "cosyvoice/vllm/cosyvoice2.py": "96810ffb9b8b649bcacccf9685bbe91ba0efaf7e4ae7594d9961af86a701f033",
    "cosyvoice/flow/flow_matching.py": "d871c37176a673bde2a1bcd7c1f1e5083afdde246d05fe5d5203fcc9a23cf98e",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source(source: Path) -> dict:
    files = {}
    for name, expected in SOURCE_HASHES.items():
        try:
            actual = hashlib.sha256((source / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        except OSError:
            actual = None
        files[name] = {"sha256": actual, "matches": actual == expected}
    return {"source_commit": SOURCE_COMMIT, "verified": all(x["matches"] for x in files.values()), "files": files}


def package_versions() -> dict:
    result = {}
    for name in ("torch", "transformers", "tensorrt", "tensorrt-cu12", "vllm", "triton", "onnxruntime", "onnxruntime-gpu"):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def matrix(packages: dict, os_name: str, source_verified: bool, artifacts: dict) -> list[dict]:
    """status 只描述实验先决条件，永不返回 production_ready。"""
    common = [] if source_verified else ["fixed_source_not_verified"]
    runtime = []
    if packages.get("torch") != "2.3.1+cu121":
        runtime.append("requires_isolated_torch_2.3.1_cu121")
    if packages.get("transformers") != "4.51.3":
        runtime.append("requires_transformers_4.51.3")
    trt = common + runtime + ([] if packages.get("tensorrt") == "10.13.3.9" or packages.get("tensorrt-cu12") == "10.13.3.9" else ["requires_tensorrt_10.13.3.9"])
    if not artifacts.get("flow_plan"):
        trt += ["missing_flow_plan_and_identity_manifest"]
    vllm = common + ([] if os_name == "Linux" else ["vllm_requires_linux"])
    if packages.get("vllm") != "0.11.0" or packages.get("transformers") != "4.57.1":
        vllm += ["requires_separate_vllm_0.11.0_transformers_4.57.1_environment"]
    if str(packages.get("torch", "")).split("+")[0] != "2.8.0":
        vllm += ["vllm_0.11.0_requires_torch_2.8.0"]
    compile_reasons = common + runtime
    if os_name != "Linux":
        compile_reasons += ["torch_2.3.1_inductor_rejects_windows"]
    if not packages.get("triton"):
        compile_reasons += ["missing_triton_backend"]
    rows = []

    def add(engine, reasons, capability, audio, text, cancellation, **extra):
        rows.append(dict(engine=engine, source_commit=extra.pop("source_commit", SOURCE_COMMIT), platform=os_name,
                         model_capability=capability, audio_streaming=audio, text_streaming=text,
                         cancellation=cancellation, status="blocked" if reasons else "needs_isolated_validation",
                         reasons=reasons, **extra))

    add("torch_fp16_hidden_only", common + runtime, "CosyVoice3 native LLM/flow/HiFT", True, True,
        "existing_stream_runtime_required", selectable_default=False)
    add("native_flow_tensorrt", trt, "CosyVoice3 flow.decoder.estimator only; adapter restricts buffered model", False, True,
        "existing_stream_runtime_required", precision="fp32 isolated model only; fp16 raw pointers incompatible", protocol_streaming="caller_can_chunk_completed_audio",
        acquisition_recommendation="none; do_not_install_legacy_runtime; inspect_existing_sdk11_first")
    add("native_vllm", vllm, "CosyVoice3 speech-token LLM; destructive export/layer removal", True, False,
        "abort_not_validated; no_bistream", registration="CosyVoice2ForCausalLM applies to CV3 too")
    add("triton_trtllm", common + ["separate_linux_stack_and_engine_build_required", "model_and_container_digests_not_pinned", "gpu_exclusive_window_required"],
        "CosyVoice3 dedicated multi-stage runtime, separate from native load_trt", True, False,
        "client_disconnect_and_request_abort_need_validation")
    add("torch_compile_flow", compile_reasons, "CosyVoice3 estimator.forward only; dynamic shapes", True, True,
        "existing_stream_runtime_required")
    add("cuda_graph", common + ["dynamic_shapes_and_mutable_kv_cache_need_static_buckets", "capture_not_implemented"],
        "no safe whole-TTS graph in fixed source", False, False, "not_validated")
    add("tts_int8_int4_fp8", common + ["no_verified_cv3_quantized_checkpoint_or_calibration_contract"],
        "research candidate; generic Qwen support is insufficient", False, False, "not_validated")
    bge = [] if str(packages.get("torch", "")).split("+")[0] == "2.8.0" else ["requires_main_cpu_torch_2.8.0"]
    add("bge_cpu_dynamic_int8", bge, "out-of-place CPU Bert Linear weights only; ranking gate required", False, False,
        "caller_owned_cpu_task", source_commit=None)
    add("remote_campus_vllm", ["remote_school_server_not_owned"], "no local inference backend switch", False, False,
        "gateway_transport_only", source_commit=None)
    return rows


def probe(source: Path, model: Path, *, include_gpu: bool = False) -> dict:
    evidence = verify_source(source)
    packages = package_versions()
    artifacts = {"flow_onnx": (model / "flow.decoder.estimator.fp32.onnx").is_file(),
                 "flow_plan": any(model.glob("flow.decoder.estimator.*.mygpu.plan")) if model.is_dir() else False}
    report = {"schema_version": 1, "python": platform.python_version(), "platform": platform.system(),
              "module_origin": str(Path(__file__).resolve()), "packages": packages, "source": evidence,
              "artifacts": artifacts, "engines": matrix(packages, platform.system(), evidence["verified"], artifacts),
              "gpu_work_performed": False}
    if include_gpu:
        # nvidia-smi 只查元数据，不调用 torch.cuda，不初始化 CUDA 上下文。
        try:
            done = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,memory.free", "--format=csv,noheader"],
                                  capture_output=True, text=True, timeout=10, check=True)
            report["gpu_metadata"] = done.stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError) as error:
            report["gpu_metadata_error"] = type(error).__name__
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--gpu-metadata", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe(args.source, args.model, include_gpu=args.gpu_metadata), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
