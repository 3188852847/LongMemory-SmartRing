"""AG C++ TensorRT路径的离线契约；不导入torch/ONNX，不执行GPU工具。"""

import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "scripts/development/cosyvoice/acceleration"
spec = importlib.util.spec_from_file_location("ag_flow_acceleration", PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
flow = importlib.import_module("ag_flow_acceleration.flow_trtexec")


def test_builder_uses_existing_cpp_tool_and_fp32_dynamic_profiles(tmp_path):
    assert all(len(value) == 64 for value in flow.PINNED.values())
    argv = flow.build_command(tmp_path / "sdk", tmp_path / "run")
    assert argv[0].endswith("trtexec.exe") and "--skipInference" in argv
    assert "--noTF32" in argv and "--memPoolSize=workspace:512M" in argv
    assert any(x.startswith("--maxShapes=x:2x80x512,mask:2x1x512") for x in argv)
    assert all(x not in argv for x in ("--fp16", "--int8", "--useCudaGraph"))


def test_runner_pins_input_path_parsing_and_does_real_transfers(tmp_path):
    argv = flow.run_command(tmp_path / "sdk", Path("D:/含 空格/run"), 127, True)
    inputs = next(x for x in argv if x.startswith("--loadInputs="))
    assert "'x':D:" in inputs and "'cond':D:" in inputs
    assert "--includeDataTransfers" in argv and "--noCudaGraph" in argv
    assert "--iterations=1" in argv and "--duration=0" in argv


@pytest.mark.parametrize("length", [0, 15, 513, 3000])
def test_profile_outside_range_refuses_before_native_call(length):
    with pytest.raises(ValueError, match="keep_eager"):
        flow.shape_arg(length)


def test_execute_refuses_unscheduled_before_probing_gpu(monkeypatch, tmp_path):
    monkeypatch.setattr(flow, "gpu_memory", lambda: pytest.fail("no GPU probe before window"))
    with pytest.raises(ValueError, match="matching_v2_project_model_receipt"):
        flow.execute(tmp_path, tmp_path, tmp_path, tmp_path, tmp_path, Path(sys.executable), "")


def test_compare_rejects_shape_nan_and_numeric_drift(tmp_path):
    import numpy as np
    case = tmp_path / flow.case_id(16, True)
    case.mkdir()
    expected = np.full(2*80*16, 0.1, dtype=np.float32)
    expected.tofile(case / "expected.bin")
    def write(values, dimensions="2x80x16"):
        (case / "trt-output.json").write_text(json.dumps([dict(name="estimator_out", dimensions=dimensions, values=values)]), encoding="utf-8")
    write(expected.tolist())
    assert flow.compare_output(tmp_path, 16, True)["allclose"]
    write(expected.tolist(), dimensions="80x2x16")
    with pytest.raises(ValueError, match="dimensions"):
        flow.compare_output(tmp_path, 16, True)
    write([float("nan")]*expected.size)
    with pytest.raises(ValueError, match="invalid"):
        flow.compare_output(tmp_path, 16, True)
    write([1.0]*expected.size)
    with pytest.raises(AssertionError):
        flow.compare_output(tmp_path, 16, True)


def test_stage_requires_window_before_creating_process(tmp_path):
    with pytest.raises(ValueError, match="gpu_window_receipt"):
        flow.bounded([], tmp_path, "mock", {}, 1)


def test_native_stage_rejects_id_without_receipt_and_outer_job(monkeypatch, tmp_path):
    monkeypatch.setattr(flow.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="sole_outer_job"):
        flow.bounded([], tmp_path, "mock", {}, 5, window_id="some-nonempty-id")
