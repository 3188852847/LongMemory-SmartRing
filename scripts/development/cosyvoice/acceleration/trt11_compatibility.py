"""TensorRT11现有SDK的静态兼容检查；不导入绑定，不解析模型或创建CUDA上下文。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from .capabilities import SOURCE_COMMIT, verify_source


def inspect_sdk(source: Path, sdk: Path) -> dict:
    source_evidence = verify_source(source)
    version_text = (sdk / "include/NvInferVersion.h").read_text(encoding="utf-8")
    defines = dict(re.findall(r"^#define\s+(\w+)\s+(\w+)", version_text, flags=re.M))
    def component(key):
        value = "NV_TENSORRT_" + key
        for _ in range(6):
            value = defines.get(value, "")
            if value.isdigit():
                return value
        raise ValueError("sdk_version_macro_unresolved")
    version = ".".join(component(key) for key in ("MAJOR", "MINOR", "PATCH", "BUILD"))
    infer = (sdk / "include/NvInfer.h").read_text(encoding="utf-8")
    runtime = (sdk / "include/NvInferRuntime.h").read_text(encoding="utf-8")
    converter = (source / "cosyvoice/utils/file_utils.py").read_text(encoding="utf-8")
    exporter = (source / "cosyvoice/bin/export_onnx.py").read_text(encoding="utf-8")
    old_flags = {
        "NetworkDefinitionCreationFlag.EXPLICIT_BATCH": ("NetworkDefinitionCreationFlag.EXPLICIT_BATCH" in converter, "kEXPLICIT_BATCH" in infer),
        "BuilderFlag.FP16": ("BuilderFlag.FP16" in converter, bool(re.search(r"\bkFP16\s*=", infer))),
    }
    reasons = []
    if not source_evidence["verified"]:
        reasons.append("fixed_source_not_verified")
    if version != "11.2.1.2":
        reasons.append("sdk_version_not_fixed_11.2.1.2")
    reasons += ["fixed_converter_uses_removed_" + name for name, (used, available) in old_flags.items() if used and not available]
    reasons += ["no_exported_cv3_onnx_or_engine_validated", "cuda13_sdk_and_cu121_torch_interop_unverified", "gpu_exclusive_window_required"]
    wheel = sdk / "python/tensorrt-11.2.1.2-cp310-none-win_amd64.whl"
    files = ("include/NvInfer.h", "include/NvInferRuntime.h", "include/NvInferVersion.h")
    return dict(schema_version=1, stage="static_sdk_only", source_commit=SOURCE_COMMIT, sdk_version=version,
                source_verified=source_evidence["verified"], sdk_header_sha256={name: hashlib.sha256((sdk / name).read_bytes()).hexdigest() for name in files},
                python_cp310_wheel_present=wheel.is_file(), native_runtime_dll_present=(sdk / "bin/nvinfer_11.dll").is_file(),
                api_flags={name: dict(used_by_fixed_converter=used, present_in_sdk=available) for name, (used, available) in old_flags.items()},
                retained_runtime_apis={name: cpp in runtime for name, cpp in {
                    "execute_async_v3": "enqueueV3", "set_tensor_address": "setTensorAddress",
                    "set_input_shape": "setInputShape", "num_io_tensors": "getNbIOTensors"}.items()},
                onnx_exporter=dict(auto_model="AutoModel" in exporter, opset18="opset_version=18" in exporter,
                                   input_names=["x", "mask", "mu", "t", "spks", "cond"], output_name="estimator_out",
                                   streaming_mode_input=False, creates_output_in_model_dir=True, executed=False),
                status="needs_isolated_validation", direct_fixed_converter_compatible=False,
                independent_candidate_possible=True, reasons=reasons,
                next_step="export_fp32_buffered_cv3_to_experiment_then_build_sdk11_engine_in_separate_process",
                installation_required_for_current_cpu_work=False, model_loaded=False, gpu_work_performed=False,
                production_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_sdk(args.source, args.sdk), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
