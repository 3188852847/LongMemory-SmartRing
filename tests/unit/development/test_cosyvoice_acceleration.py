"""AG 引擎边界与合成 PCM 验证；不加载真实模型、CUDA、服务或个人数据。"""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "scripts/development/cosyvoice/acceleration"
spec = importlib.util.spec_from_file_location("ag_acceleration", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
cap = importlib.import_module("ag_acceleration.capabilities")
adapters = importlib.import_module("ag_acceleration.adapters")
bench = importlib.import_module("ag_acceleration.benchmark")
bge_bench = importlib.import_module("ag_acceleration.bge_benchmark")
trt11 = importlib.import_module("ag_acceleration.trt11_compatibility")
cosy_runner = importlib.import_module("ag_acceleration.cosy_runner")


def test_import_origin_and_no_gpu_import_in_clean_process():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import acceleration.capabilities, acceleration.adapters, acceleration.benchmark, acceleration.bge_benchmark, acceleration.cosy_runner, acceleration.trt11_compatibility; assert not any(n in sys.modules for n in ['torch','transformers','tensorrt','vllm'])"
    subprocess.run([sys.executable, "-I", "-B", "-c", code, str(PACKAGE.parent)], check=True, cwd=ROOT)
    assert Path(cap.__file__).resolve().is_relative_to(ROOT)


def test_fixed_source_missing_and_drift(tmp_path, monkeypatch):
    file = tmp_path / "sample.py"
    file.write_text("verified", encoding="utf-8")
    monkeypatch.setattr(cap, "SOURCE_HASHES", {"sample.py": hashlib.sha256(b"verified").hexdigest()})
    assert cap.verify_source(tmp_path)["verified"]
    file.write_text("different", encoding="utf-8")
    assert not cap.verify_source(tmp_path)["verified"]
    assert not cap.verify_source(tmp_path / "missing")["verified"]


def test_windows_environment_reports_real_blockers():
    rows = {r["engine"]: r for r in cap.matrix({"torch": "2.3.1+cu121", "transformers": "4.51.3"}, "Windows", True, {})}
    assert rows["torch_fp16_hidden_only"]["status"] == "needs_isolated_validation"
    assert "vllm_requires_linux" in rows["native_vllm"]["reasons"]
    assert not rows["native_vllm"]["text_streaming"]
    assert "torch_2.3.1_inductor_rejects_windows" in rows["torch_compile_flow"]["reasons"]
    assert "requires_tensorrt_10.13.3.9" in rows["native_flow_tensorrt"]["reasons"]
    assert rows["remote_campus_vllm"]["source_commit"] is None
    assert all(r["status"] != "production_ready" for r in rows.values())


def test_compile_and_trt_never_start_without_window(tmp_path):
    torch = SimpleNamespace()
    result = adapters.install_flow_trt(object(), source=tmp_path, plan=tmp_path, manifest=tmp_path, torch=torch, context=adapters.ExperimentContext())
    assert result.reason == "requires_isolated_instance_and_exclusive_window"
    result = adapters.install_flow_compile(object(), source=tmp_path, torch=torch, context=adapters.ExperimentContext(True, "window"), os_name="Windows")
    assert result.reason == "torch_2.3.1_inductor_rejects_windows"


def test_gpu_guard_rejects_wrong_source_and_import(tmp_path, monkeypatch):
    context = adapters.ExperimentContext(True, "receipt")
    assert adapters._gpu_guard(object(), tmp_path, object(), context) == "fixed_source_not_verified"
    monkeypatch.setattr(adapters, "verify_source", lambda _: {"verified": True})
    torch = SimpleNamespace(__version__="2.3.1+cu121")
    assert adapters._gpu_guard(object(), tmp_path, torch, context) == "unsupported_model_class"
    CosyVoice3Model = type("CosyVoice3Model", (), {})
    assert adapters._gpu_guard(CosyVoice3Model(), tmp_path, torch, context) == "model_import_source_mismatch"


@pytest.fixture
def trt_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "_gpu_guard", lambda *args: None)
    original = object()
    model = SimpleNamespace(flow=SimpleNamespace(decoder=SimpleNamespace(estimator=original)), device="cuda:0", fp16=False)
    plan = tmp_path / "flow.plan"
    plan.write_bytes(b"synthetic engine; not a real TRT plan")
    identity = dict(source_commit=cap.SOURCE_COMMIT, plan_sha256=cap.sha256(plan), precision="fp32", tensorrt_version="10.13.3.9", gpu_name="mock")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(identity), encoding="utf-8")
    kwargs = dict(source=tmp_path, plan=plan, manifest=manifest, torch=SimpleNamespace(cuda=SimpleNamespace(get_device_name=lambda _: "mock")), context=adapters.ExperimentContext(True, "mock-window"))
    return model, original, identity, kwargs


def test_trt_construct_before_replace_and_restore(trt_setup):
    model, original, identity, kwargs = trt_setup
    candidate = object()
    result = adapters.install_flow_trt(model, **kwargs, loader=lambda *args: candidate)
    assert result.applied and model.flow.decoder.estimator is candidate
    assert result.restore() and model.flow.decoder.estimator is original
    assert not result.restore()


@pytest.mark.parametrize("field,value,reason", [
    ("plan_sha256", "bad", "engine_identity_mismatch"),
    ("source_commit", "other", "engine_identity_mismatch"),
    ("precision", "fp16", "requires_fp32_flow_plan"),
    ("gpu_name", "other", "engine_gpu_mismatch"),
    ("tensorrt_version", "11.2", "engine_tensorrt_version_mismatch"),
])
def test_trt_manifest_mismatch_never_loads(trt_setup, field, value, reason):
    model, original, identity, kwargs = trt_setup
    identity[field] = value
    kwargs["manifest"].write_text(json.dumps(identity), encoding="utf-8")
    def no_load(*args):
        pytest.fail("must not load incompatible engine")
    result = adapters.install_flow_trt(model, **kwargs, loader=no_load)
    assert not result.applied and result.reason == reason
    assert model.flow.decoder.estimator is original


def test_trt_exception_keeps_original_and_redacts(trt_setup):
    model, original, identity, kwargs = trt_setup
    def fail(*args):
        raise RuntimeError("private exception details")
    result = adapters.install_flow_trt(model, **kwargs, loader=fail)
    assert result.reason == "engine_load_failed:RuntimeError"
    assert model.flow.decoder.estimator is original


def test_trt_rejects_fp16_pointers_and_unverified_streaming(trt_setup):
    model, original, identity, kwargs = trt_setup
    model.fp16 = True
    assert adapters.install_flow_trt(model, **kwargs).reason == "fp32_plan_requires_separate_fp32_model"
    model.fp16 = False
    assert adapters.install_flow_trt(model, **kwargs, model_streaming=True).reason == "fixed_onnx_streaming_mask_not_validated"
    assert model.flow.decoder.estimator is original


def test_restore_does_not_clobber_later_adapter(trt_setup):
    model, original, identity, kwargs = trt_setup
    result = adapters.install_flow_trt(model, **kwargs, loader=lambda *args: object())
    later = object()
    model.flow.decoder.estimator = later
    assert not result.restore() and model.flow.decoder.estimator is later
    result = adapters.install_flow_trt(model, **kwargs, loader=lambda *args: object())
    delattr(model.flow.decoder, "estimator")
    assert not result.restore()


def test_real_cpu_module_replacement_preserves_registered_original():
    import torch
    owner = torch.nn.Module()
    original = torch.nn.Linear(2, 2)
    owner.estimator = original
    result = adapters._replace(owner, "estimator", object(), "mock")
    assert "estimator" not in owner._modules
    assert result.restore() and owner._modules["estimator"] is original


def test_lazy_compile_failure_restores_without_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "_gpu_guard", lambda *args: None)
    class Estimator:
        def forward(self, value):
            return value + 1
    estimator = Estimator()
    def compile_fn(fn, **kwargs):
        assert kwargs["dynamic"] is True
        def broken(*args, **kwargs):
            raise RuntimeError("compile failed")
        return broken
    model = SimpleNamespace(flow=SimpleNamespace(decoder=SimpleNamespace(estimator=estimator)))
    result = adapters.install_flow_compile(model, source=tmp_path, torch=SimpleNamespace(compile=compile_fn), context=adapters.ExperimentContext(True, "window"), os_name="Linux")
    with pytest.raises(adapters.CandidateExecutionError):
        estimator.forward(2)
    assert not result.applied and estimator.forward(2) == 3
    assert "forward" not in vars(estimator)


def test_vllm_never_creates_partial_or_inplace_model(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "verify_source", lambda _: {"verified": True})
    context = adapters.ExperimentContext(True, "window")
    args = dict(source=tmp_path / "source", staged_model=tmp_path / "experiment/model", experiment_root=tmp_path / "experiment", context=context, versions={"vllm": "0.11.0", "transformers": "4.57.1", "torch": "2.8.0+cu128"}, os_name="Linux")
    assert adapters.create_native_vllm(**args).reason == "staged_model_incomplete_no_download"
    args["staged_model"] = tmp_path / "source/model"
    assert adapters.create_native_vllm(**args).reason == "model_must_be_staged_outside_source_inside_experiment"
    args["os_name"] = "Windows"
    assert adapters.create_native_vllm(**args).reason == "vllm_requires_linux"


def test_vllm_factory_receives_cv3_options_without_trt(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "verify_source", lambda _: {"verified": True})
    model = tmp_path / "runs/model"
    for name in ("cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "speech_tokenizer_v3.onnx", "campplus.onnx", "CosyVoice-BlankEN/config.json"):
        file = model / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic")
    calls = []
    def factory(path, **kwargs):
        calls.append(kwargs)
        return object()
    args = dict(source=tmp_path / "source", staged_model=model, experiment_root=tmp_path / "runs", context=adapters.ExperimentContext(True, "window"), versions={"vllm": "0.11.0", "transformers": "4.57.1", "torch": "2.8.0+cu128"}, os_name="Linux", factory=factory)
    assert adapters.create_native_vllm(**args).applied
    assert calls == [{"load_trt": False, "load_vllm": True, "fp16": False}]
    (model / "vllm").mkdir()
    assert adapters.create_native_vllm(**args).reason == "existing_vllm_export_requires_separate_identity_review"


def test_real_cpu_quantization_keeps_baseline_and_checks_ranking():
    import torch
    class TinyBert(torch.nn.Module):
        config = SimpleNamespace(model_type="bert")
        def __init__(self):
            super().__init__()
            self.linear = torch.nn.Linear(4, 3)
        def forward(self, x):
            return self.linear(x)
    torch.manual_seed(17)
    model = TinyBert().eval()
    x = torch.randn(8, 4)
    before = model(x).detach().clone()
    with pytest.warns(DeprecationWarning):
        result = adapters.bge_cpu_int8_candidate(model, torch=torch)
    assert result.applied and result.candidate is not model
    assert torch.equal(model(x), before)
    after = result.candidate(x)
    assert torch.isfinite(after).all() and (before - after).abs().max().item() < 0.05
    assert bench.ranking_gate([[0.9, 0.3, 0.1]], [[0.88, 0.31, 0.1]], [{0}], k=1)["automatic_passed"]
    assert not bench.ranking_gate([[0.9, 0.3]], [[0.1, 0.9]], [{0}], k=1)["automatic_passed"]


def pcm(size=1600, value=0.1):
    return bench.AudioChunk((value,) * size, 16000)


def test_first_silent_chunk_is_not_first_effective_audio():
    ticks = iter([0, 0.1, 0.4, 0.5])
    result = bench.measure(lambda *args: iter([pcm(value=0), pcm()]), "short", 17, clock=lambda: next(ticks))
    assert result["first_pcm_ms"] == 100
    assert result["first_voiced_pcm_ms"] == 400
    assert result["underflows"] == 1 and result["worst_gap_ms"] == 200
    assert not result["quality_passed"]


def test_cancel_closes_generator_and_delivers_no_later_chunk():
    seen = []
    def runner(case, seed, cancel):
        try:
            yield pcm()
            seen.append("late delivery")
            yield pcm()
        finally:
            seen.append("closed")
    result = bench.measure(runner, "cancel", 17, cancel_after_chunks=1)
    assert seen == ["closed"] and result["chunks"] == 1
    assert result["cancel_requested"] and result["cancel_close_ms"] is not None


@pytest.mark.parametrize("chunks", [[], [pcm(value=0)], [bench.AudioChunk((float("nan"),), 16000)], [pcm(), bench.AudioChunk((0.1,) * 100, 24000)]])
def test_empty_silent_invalid_audio_cannot_pass(chunks):
    result = bench.measure(lambda *args: iter(chunks), "short", 17)
    assert not bench.audio_gate(result, result)["eligible_for_review"]


def test_runner_initialization_failure_is_reported_without_details():
    def fail(*args):
        raise ValueError("private text")
    result = bench.measure(fail, "short", 17)
    assert result["error"] == "ValueError" and "private" not in json.dumps(result)


def test_quality_gate_keeps_baseline_until_voice_and_cancel_verified():
    result = bench.measure(lambda *args: iter([pcm()]), "short", 17)
    gate = bench.audio_gate(result, result)
    assert gate["automatic_passed"] and gate["action"] == "keep_baseline"
    assert bench.audio_gate(result, result, human_voice_passed=True, cancellation_passed=True)["eligible_for_review"]
    assert "unpaired_case_or_seed" in bench.audio_gate(result, dict(result, seed=29))["reasons"]
    assert "clipping_regression" in bench.audio_gate(result, dict(result, clipping_fraction=0.1))["reasons"]


@pytest.mark.parametrize("concurrency", [1, 2, 4])
def test_bounded_concurrency_is_separate_from_engine_speed_claim(concurrency):
    report = bench.paired_benchmark({"base": lambda *args: iter([pcm()]), "candidate": lambda *args: iter([pcm()])}, ["short"], seeds=(17, 29), concurrency=concurrency)
    assert len(report["records"]) == 4 * concurrency
    assert not report["real_gpu_verified"] and not report["device_first_answer_verified"]
    assert [r["engine"] for r in report["records"]][::concurrency] == ["base", "candidate", "candidate", "base"]


def test_bge_metadata_reads_header_only_without_loading_payload(tmp_path):
    import struct
    (tmp_path / "config.json").write_text(json.dumps(dict(model_type="bert", num_hidden_layers=4, hidden_size=512)), encoding="utf-8")
    header = json.dumps({"embeddings.word_embeddings.weight": {"shape": [2, 2], "dtype": "F32", "data_offsets": [0, 16]},
                         "encoder.layer.0.dense.weight": {"shape": [2, 2], "dtype": "F32", "data_offsets": [16, 32]}}).encode("utf-8")
    (tmp_path / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header)
    report = bge_bench.metadata_plan(tmp_path)
    assert report["stage"] == "metadata_only_no_model_load" and not report["model_load_executed"]
    assert report["estimated_int8_payload_mib"] == 20 / 2**20
    assert report["maximum_forward_calls"] == 40


class SyntheticBGE:
    def __init__(self):
        self._model = object()
        self._tokenizer = lambda text: {"input_ids": list(range(len(text) + 2))}
    def encode_query(self, text):
        if not text:
            raise ValueError("empty")
        relevant = next(labels for _, case, labels in bge_bench.QUERIES if case == text)
        return [float(i in relevant) for i in range(12)]
    def encode_documents(self, texts):
        rows = []
        for text in texts:
            if not text or len(text) > 510:
                raise ValueError("empty_or_overlong")
            index = bge_bench.DOCUMENTS.index(text) if text in bge_bench.DOCUMENTS else 0
            rows.append([float(i == index) for i in range(12)])
        return rows


def test_bge_pair_matrix_existing_and_rebuilt_synthetic_indexes(monkeypatch):
    monkeypatch.setattr(bge_bench, "bge_cpu_int8_candidate", lambda *args, **kwargs: SimpleNamespace(applied=True, candidate=object()))
    encoder = SyntheticBGE()
    original = encoder._model
    clock_values = iter(i / 1000 for i in range(100))
    result = bge_bench.run_loaded(encoder, object(), clock=lambda: next(clock_values), expected_dimensions=12)
    assert encoder._model is original
    assert len(result["records"]) == 30 and result["all_automatic_gates_passed"]
    assert result["ranking_gates"]["existing_fp32_synthetic_index"]["candidate_recall_at_k"] == 1
    assert result["timings_median_ms"]["8"]["fp32_over_int8_ratio"] == pytest.approx(1)
    assert not result["production_ready"] and not result["final_memory_answers_verified"]


def test_bge_pair_restores_model_when_boundary_or_inference_fails(monkeypatch):
    monkeypatch.setattr(bge_bench, "bge_cpu_int8_candidate", lambda *args, **kwargs: SimpleNamespace(applied=True, candidate=object()))
    encoder = SyntheticBGE()
    original = encoder._model
    encoder._tokenizer = lambda text: {"input_ids": []}
    with pytest.raises(RuntimeError, match="boundary_fixture"):
        bge_bench.run_loaded(encoder, object(), expected_dimensions=12)
    assert encoder._model is original


def test_bge_execute_requires_window_before_spawning(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not spawn"))
    with pytest.raises(ValueError, match="window_receipt"):
        bge_bench.execute_owned(tmp_path, "")


def test_trt11_reports_removed_apis_without_importing_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(trt11, "verify_source", lambda _: {"verified": True})
    source = tmp_path / "source"
    sdk = tmp_path / "sdk"
    for path in (source / "cosyvoice/utils", source / "cosyvoice/bin", sdk / "include"):
        path.mkdir(parents=True)
    (source / "cosyvoice/utils/file_utils.py").write_text("NetworkDefinitionCreationFlag.EXPLICIT_BATCH; BuilderFlag.FP16", encoding="utf-8")
    (source / "cosyvoice/bin/export_onnx.py").write_text("AutoModel; opset_version=18", encoding="utf-8")
    (sdk / "include/NvInferVersion.h").write_text("\n".join(f"#define TRT_{key}_ENTERPRISE {value}\n#define NV_TENSORRT_{key} TRT_{key}_ENTERPRISE" for key, value in zip(("MAJOR", "MINOR", "PATCH", "BUILD"), (11, 2, 1, 2))), encoding="utf-8")
    (sdk / "include/NvInfer.h").write_text("kSTRONGLY_TYPED", encoding="utf-8")
    (sdk / "include/NvInferRuntime.h").write_text("enqueueV3 setTensorAddress setInputShape getNbIOTensors", encoding="utf-8")
    result = trt11.inspect_sdk(source, sdk)
    assert result["sdk_version"] == "11.2.1.2" and result["independent_candidate_possible"]
    assert not result["direct_fixed_converter_compatible"] and not result["gpu_work_performed"]
    assert all(result["retained_runtime_apis"].values())
    assert len([r for r in result["reasons"] if "removed" in r]) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object")
def test_resource_job_limits_apply_to_launcher_and_python_child():
    job = bge_bench.WindowsResourceJob()
    process = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import os,time; print(os.getpid(),flush=True); time.sleep(.2)"], stdout=subprocess.PIPE)
    try:
        job.assign(process)
        stdout, _ = process.communicate(timeout=3)
        snapshot = job.snapshot()
        assert snapshot["process_memory_limit_bytes"] == 2048 * 2**20
        assert snapshot["job_memory_limit_bytes"] == 2048 * 2**20
        assert snapshot["affinity_mask"].bit_count() <= 2
        assert snapshot["peak_job_memory_bytes"] > 0
        assert int(stdout.strip()) > 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        job.close()


def test_cosy_runner_decodes_actual_wav_closes_cancel_and_disables_cache(monkeypatch):
    import io
    import struct
    import threading
    import wave
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(struct.pack("<160h", *([3276] * 160)))
    calls, seeds, closed = [], [], []
    class Synth:
        stream_runtime = SimpleNamespace(applied=True)
        _torch = SimpleNamespace(manual_seed=seeds.append)
        def stream_chunks(self, text, *, use_cache, model_streaming, cancel_event):
            calls.append((use_cache, model_streaming))
            try:
                yield data.getvalue()
                yield data.getvalue()
            finally:
                closed.append(True)
    monkeypatch.setattr(cosy_runner, "_service_origin", lambda _: ROOT / "scripts/development/cosyvoice/service.py")
    runner = cosy_runner.make_runner(Synth(), context=adapters.ExperimentContext(True, "mock-gpu-window"), model_streaming=True)
    cancel = threading.Event()
    iterator = runner("short", 17, cancel)
    first = next(iterator)
    assert first.sample_rate == 16000 and len(first.samples) == 160
    assert first.samples[0] == pytest.approx(3276 / 32768)
    cancel.set()
    assert list(iterator) == [] and closed == [True]
    assert calls == [(False, True)] and seeds == [17]
    assert cosy_runner.evaluation_contract()["status"] == "needs_isolated_validation"


def test_cosy_runner_refuses_unscheduled_or_foreign_synth():
    with pytest.raises(ValueError, match="exclusive_gpu_window"):
        cosy_runner.make_runner(object(), context=adapters.ExperimentContext(), model_streaming=False)


def test_quantized_embedding_identity_never_reuses_baseline_or_mutates_recipe():
    baseline = dict(provider="local_bge", dtype="float32", model="BAAI/bge-small-zh-v1.5", pooling="cls", normalization="l2")
    before = json.dumps(baseline, sort_keys=True)
    identity = adapters.bge_candidate_identity(baseline)
    assert identity["baseline_identity"] != identity["candidate_identity"]
    assert identity["recipe_changed"] and not identity["personal_index_migration_authorized"]
    assert identity["candidate_metadata"]["quantization_recipe"]["dimensions"] == 512
    assert json.dumps(baseline, sort_keys=True) == before
    identity["candidate_metadata"]["quantization_recipe"]["module_types"].append("must_not_leak")
    assert "must_not_leak" not in adapters.BGE_INT8_RECIPE["module_types"]
