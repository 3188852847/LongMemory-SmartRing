"""隔离实例上的可撤回候选；不接日用服务，不隐式构建/下载引擎。

所有 GPU API 必须由调用方取得主会话独占窗口后调用。window_id 是调度收据，
不是通过检查空闲显存自动获得的许可。安装、撤回均要求无活跃请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from importlib import import_module
import inspect
import json
from pathlib import Path
import platform
from typing import Any, Callable

from .capabilities import SOURCE_COMMIT, package_versions, sha256, verify_source

BGE_INT8_RECIPE = {"algorithm": "torch.ao.quantization.quantize_dynamic", "module_types": ["torch.nn.Linear"],
                   "weight_dtype": "qint8", "activation_quantization": "dynamic", "inplace": False,
                   "pooling": "cls", "normalization": "l2", "dimensions": 512, "max_tokens": 512}


def bge_candidate_identity(baseline_metadata: dict) -> dict:
    """量化是新的embedding recipe/身份；绝不沿用原provider_identity写现有索引。"""
    import hashlib
    metadata = dict(deepcopy(baseline_metadata), provider="local_bge_dynamic_int8_candidate",
                    dtype="mixed_fp32_and_dynamic_qint8_linear", quantization_recipe=deepcopy(BGE_INT8_RECIPE))
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
    return dict(baseline_identity=digest(baseline_metadata), candidate_identity=digest(metadata),
                candidate_metadata=metadata, recipe_changed=True, personal_index_migration_authorized=False,
                compatibility_scope="synthetic_old_index_query_and_synthetic_rebuilt_index_only")


class CandidateExecutionError(RuntimeError):
    """丢弃本次候选输出，恢复后从新请求运行基线；不在半个响应中拼接回退。"""


@dataclass(frozen=True)
class ExperimentContext:
    isolated_instance: bool = False
    window_id: str = ""


@dataclass
class Adapter:
    applied: bool
    reason: str
    candidate: Any = None
    _owner: Any = None
    _name: str = ""
    _original: Any = None
    _had_local: bool = False
    recipe: dict | None = None

    def restore(self) -> bool:
        if not self.applied or self._owner is None:
            return False
        if getattr(self._owner, self._name, None) is not self.candidate:
            self.applied, self.reason = False, "restore_skipped_target_changed"
            return False
        if self._had_local:
            _assign(self._owner, self._name, self._original)
        else:
            delattr(self._owner, self._name)
        self.applied, self.reason = False, "restored"
        return True


def _assign(owner: Any, name: str, value: Any):
    # nn.Module 不允许把已注册子模块直接换成上游的非 Module TRT wrapper。
    if name in getattr(owner, "_modules", {}):
        delattr(owner, name)
    setattr(owner, name, value)


def _replace(owner: Any, name: str, candidate: Any, reason: str) -> Adapter:
    had_local = name in vars(owner) or name in getattr(owner, "_modules", {})
    result = Adapter(True, reason, candidate, owner, name, getattr(owner, name), had_local)
    try:
        _assign(owner, name, candidate)
    except Exception:
        _assign(owner, name, result._original)
        raise
    return result


def _gpu_guard(model: Any, source: Path, torch: Any, context: ExperimentContext) -> str | None:
    if not context.isolated_instance or not context.window_id.strip():
        return "requires_isolated_instance_and_exclusive_window"
    if not verify_source(source)["verified"]:
        return "fixed_source_not_verified"
    if getattr(torch, "__version__", None) != "2.3.1+cu121":
        return "unsupported_torch_version"
    if type(model).__name__ != "CosyVoice3Model":
        return "unsupported_model_class"
    try:
        origin = Path(inspect.getfile(type(model))).resolve()
    except (TypeError, OSError):
        return "model_source_unavailable"
    if origin != (source / "cosyvoice/cli/model.py").resolve():
        return "model_import_source_mismatch"
    if any(getattr(model, name, None) for name in ("tts_speech_token_dict", "llm_end_dict", "hift_cache_dict")):
        return "active_request_state"
    if getattr(model.flow.decoder.estimator, "training", True):
        return "estimator_not_eval"
    if not torch.cuda.is_available() or str(model.device).split(":")[0] != "cuda":
        return "cuda_required"
    return None


def install_flow_trt(model: Any, *, source: Path, plan: Path, manifest: Path,
                     torch: Any, context: ExperimentContext,
                     loader: Callable | None = None, model_streaming: bool = False) -> Adapter:
    """只加载预构建且绑定本机/源码/精度的 plan，原 estimator 保持到构造成功。

    manifest 必须含 source_commit/plan_sha256/tensorrt_version/gpu_name/precision。
    拒绝 fp16 DiT plan：固定上游明确警告性能。fp32 plan 必须配独立 fp32 实例，
    上游直接传数据指针，不能把现有 fp16 输入绑定到 fp32 plan。
    不调用上游 load_trt，避免缺 plan 自动编译及先 del estimator 的失败窗口。
    """
    error = _gpu_guard(model, source, torch, context)
    if error:
        return Adapter(False, error)
    if getattr(model, "fp16", True):
        return Adapter(False, "fp32_plan_requires_separate_fp32_model")
    if model_streaming:
        return Adapter(False, "fixed_onnx_streaming_mask_not_validated")
    try:
        identity = json.loads(manifest.read_text(encoding="utf-8"))
        if identity["source_commit"] != SOURCE_COMMIT or identity["plan_sha256"] != sha256(plan):
            return Adapter(False, "engine_identity_mismatch")
        if identity["precision"] != "fp32":
            return Adapter(False, "requires_fp32_flow_plan")
        if identity["gpu_name"] != torch.cuda.get_device_name(model.device):
            return Adapter(False, "engine_gpu_mismatch")
        # 真正调用之前才导入 TensorRT；能力检查和 CPU 测试不会触碰 CUDA。
        if loader is None:
            import tensorrt as trt
            from cosyvoice.utils.common import TrtContextWrapper
            if trt.__version__ != "10.13.3.9" or identity["tensorrt_version"] != trt.__version__:
                return Adapter(False, "engine_tensorrt_version_mismatch")
            with trt.Runtime(trt.Logger(trt.Logger.WARNING)) as runtime:
                engine = runtime.deserialize_cuda_engine(plan.read_bytes())
            if engine is None:
                return Adapter(False, "engine_deserialization_failed")
            names = ("x", "mask", "mu", "t", "spks", "cond", "estimator_out")
            shapes = ((2, 80, -1), (2, 1, -1), (2, 80, -1), (2,), (2, 80), (2, 80, -1), (2, 80, -1))
            if engine.num_io_tensors != 7 or tuple(engine.get_tensor_name(i) for i in range(7)) != names:
                return Adapter(False, "engine_tensor_order_mismatch")
            if any(engine.get_tensor_dtype(name) != trt.DataType.FLOAT or tuple(engine.get_tensor_shape(name)) != shape for name, shape in zip(names, shapes)):
                return Adapter(False, "engine_tensor_dtype_or_shape_mismatch")
            candidate = TrtContextWrapper(engine, trt_concurrent=1, device=model.device)
        else:
            # 测试注入负责同样的版本核验；不作为生产绕过入口接线。
            if identity["tensorrt_version"] != "10.13.3.9":
                return Adapter(False, "engine_tensorrt_version_mismatch")
            candidate = loader(plan, model.device)
    except Exception as error:
        return Adapter(False, "engine_load_failed:" + type(error).__name__)
    return _replace(model.flow.decoder, "estimator", candidate, "flow_trt_candidate_unvalidated")


def install_flow_compile(model: Any, *, source: Path, torch: Any,
                         context: ExperimentContext, os_name: str | None = None) -> Adapter:
    """只编译无请求字典的 estimator.forward，保留 hidden-head bypass 与采样。

    首次实际调用可能才触发编译；失败时撤回并抛出可识别异常，由调用方丢弃整次
    请求再跑基线。dynamic=True 不宣称没有重编译，必须同时记录冷启动/稳态。
    """
    if (os_name or platform.system()) != "Linux":
        return Adapter(False, "torch_2.3.1_inductor_rejects_windows")
    error = _gpu_guard(model, source, torch, context)
    if error:
        return Adapter(False, error)
    estimator = model.flow.decoder.estimator
    if "forward" in vars(estimator) or any(getattr(estimator, key, None) for key in ("_forward_hooks", "_forward_pre_hooks")):
        return Adapter(False, "estimator_forward_already_wrapped")
    original = estimator.forward
    try:
        compiled = torch.compile(original, backend="inductor", dynamic=True, fullgraph=False, mode="default")
    except Exception as error:
        return Adapter(False, "compile_setup_failed:" + type(error).__name__)
    result = Adapter(False, "initializing")

    def guarded(*args, **kwargs):
        try:
            return compiled(*args, **kwargs)
        except Exception as error:
            result.restore()
            result.reason = "compile_execution_failed:" + type(error).__name__
            raise CandidateExecutionError(result.reason) from None

    installed = _replace(estimator, "forward", guarded, "flow_compile_candidate_unvalidated")
    result.__dict__.update(installed.__dict__)
    return result


def bge_cpu_int8_candidate(model: Any, *, torch: Any) -> Adapter:
    """生成独立 CPU Bert 候选，永不替换调用方检索模型或写持久索引。

    使用现有主环境 torch2.8，无新依赖；只有检索排名/召回与速度一起验收才能
    交给调用方选用。动态量化不是 TTS GPU INT8 开关。
    """
    if str(getattr(torch, "__version__", "")).split("+")[0] != "2.8.0":
        return Adapter(False, "unsupported_cpu_torch_version", model)
    if getattr(getattr(model, "config", None), "model_type", None) != "bert":
        return Adapter(False, "requires_cpu_bert_model", model)
    if model.training or any(p.device.type != "cpu" for p in model.parameters()):
        return Adapter(False, "requires_eval_cpu_model", model)
    try:
        candidate = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=False)
        return Adapter(True, "cpu_int8_candidate_requires_ranking_gate", candidate, recipe=deepcopy(BGE_INT8_RECIPE))
    except Exception as error:
        return Adapter(False, "quantization_failed:" + type(error).__name__, model)


def create_native_vllm(*, source: Path, staged_model: Path, experiment_root: Path,
                       context: ExperimentContext, versions: dict | None = None,
                       os_name: str | None = None, factory: Callable | None = None) -> Adapter:
    """仅在独立进程、独占窗口创建 vLLM 候选，不把现有日用对象改装为 vLLM。

    staged_model 必须由所有者事先在实验目录准备；上游会在其 vllm 子目录导出、
    更改语音 head 并删除模型层，不能对日用模型目录调用。本模块不复制权重。
    vLLM0.11.0 路径独立于原 torch2.3.1 环境；拒绝文字生成器模式。
    """
    if not context.isolated_instance or not context.window_id.strip():
        return Adapter(False, "requires_isolated_process_and_exclusive_window")
    if (os_name or platform.system()) != "Linux":
        return Adapter(False, "vllm_requires_linux")
    if not verify_source(source)["verified"]:
        return Adapter(False, "fixed_source_not_verified")
    versions = package_versions() if versions is None else versions
    if versions.get("vllm") != "0.11.0" or versions.get("transformers") != "4.57.1":
        return Adapter(False, "requires_separate_vllm_0.11.0_transformers_4.57.1_environment")
    if str(versions.get("torch", "")).split("+")[0] != "2.8.0":
        return Adapter(False, "vllm_0.11.0_requires_torch_2.8.0")
    staged_model, experiment_root = staged_model.resolve(), experiment_root.resolve()
    if staged_model == experiment_root or experiment_root not in staged_model.parents or source.resolve() in staged_model.parents:
        return Adapter(False, "model_must_be_staged_outside_source_inside_experiment")
    required = ("cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx", "campplus.onnx", "CosyVoice-BlankEN/config.json")
    if not all((staged_model / name).is_file() for name in required):
        return Adapter(False, "staged_model_incomplete_no_download")
    # 已有导出可能来自另一个权重/精度；不凭目录存在就沿用。
    if (staged_model / "vllm").exists():
        return Adapter(False, "existing_vllm_export_requires_separate_identity_review")
    try:
        if factory is None:
            cosy = import_module("cosyvoice.cli.cosyvoice")
            if Path(cosy.__file__).resolve() != (source / "cosyvoice/cli/cosyvoice.py").resolve():
                return Adapter(False, "model_import_source_mismatch")
            from vllm import ModelRegistry
            from cosyvoice.vllm.cosyvoice2 import CosyVoice2ForCausalLM
            ModelRegistry.register_model("CosyVoice2ForCausalLM", CosyVoice2ForCausalLM)
            factory = cosy.CosyVoice3
        candidate = factory(str(staged_model), load_trt=False, load_vllm=True, fp16=False)
        return Adapter(True, "native_vllm_candidate_no_bistream_abort_unverified", candidate)
    except Exception as error:
        return Adapter(False, "vllm_candidate_failed_discard_process:" + type(error).__name__)
