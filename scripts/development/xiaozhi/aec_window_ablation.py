"""固定公开输入的Hann离线四臂消融；不修改生产代码、不连接日用。"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace
import wave


ROOT = Path(__file__).resolve().parents[3]
BASE_HARNESS_HASH = "f5bae9147f166368d070c4c91fd290077a21964668e6a200701a21f3f6f84932"
BASE_SUMMARY_HASH = "4b538ed63bf5f4fc20b36e194bdc4372d3f6a3e3e330f73234a42e77376ce3dd"
BASE_CONFIG_HASH = "f69cfbdd1c28f75768b9495197fffc9e6b53068f6b9bd25fe4142a4eb5d235dc"
ARMS = ("original", "identity", "hann_only", "raw_frame_spectral_gain")
ARM_DEFINITIONS = {
    "original": "Pinned original DSP, read-only actual-selection probe only",
    "identity": "Same selection and bypass predicates; return original PCM before processing",
    "hann_only": "result_mag=mic_mag; omit extra 0.3 suppression; retain Hann FFT and direct inverse",
    "raw_frame_spectral_gain": "Original selection/magnitudes/gain/0.3; apply bounded bin gain to unwindowed frame FFT",
}


def load_base():
    path = Path(__file__).with_name("public_aec_replay.py")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != BASE_HARNESS_HASH:
        raise ValueError("baseline_harness_changed")
    value = ModuleType("frozen_public_aec_replay")
    value.__file__ = str(path)
    exec(compile(blob, str(path), "exec"), value.__dict__)
    return value


def variant(node, arm, base):
    if arm not in ARMS:
        raise ValueError("unknown_ablation_arm")
    result = base.instrument_selection(node)
    body = next(item for item in result.body if isinstance(item, ast.Try)).body
    def assignment(name):
        matches = [item for item in body if isinstance(item, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == name for target in item.targets)]
        if len(matches) != 1:
            raise ValueError("unexpected_ablation_assignment")
        return matches[0]
    if arm == "identity":
        hooks = [index for index, item in enumerate(body) if isinstance(item, ast.Expr)
                 and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name)
                 and item.value.func.id == "_selected_reference"]
        if len(hooks) != 1:
            raise ValueError("unexpected_selection_probe")
        body.insert(hooks[0] + 1, ast.Return(ast.Name("pcm_frame", ast.Load())))
    elif arm == "hann_only":
        assignment("result_mag").value = ast.Name("mic_mag", ast.Load())
        high = [index for index, item in enumerate(body) if isinstance(item, ast.If)
                and {"best_corr", "ref_rms"} <= {name.id for name in ast.walk(item.test) if isinstance(name, ast.Name)}]
        if len(high) != 1:
            raise ValueError("unexpected_high_confidence_branch")
        body[high[0]] = ast.copy_location(ast.Pass(), body[high[0]])
    elif arm == "raw_frame_spectral_gain":
        # 非整体放大/逐样本除窗。原窗域增益逐频率作用于未加窗帧；零能量bin取1。
        assignment("result_fft").value = ast.parse(
            "np.fft.rfft(mic_audio) * np.divide(result_mag, mic_mag, "
            "out=np.ones_like(mic_mag), where=mic_mag != 0)", mode="eval").body
    return ast.fix_missing_locations(result)


def read_pcm(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError("unexpected_frozen_pcm_format")
        if wav.getnframes() > 160000:
            raise ValueError("input_exceeds_ten_seconds")
        return wav.readframes(wav.getnframes())


def prepare(args, base):
    run = args.baseline_run
    summary = json.loads(base.checked((run / "summary.json").read_bytes(), BASE_SUMMARY_HASH))
    base.checked((run / "config.json").read_bytes(), BASE_CONFIG_HASH)
    if summary["state"] != "complete" or not 4 <= len(summary["cases"]) <= 8:
        raise ValueError("invalid_frozen_baseline")
    for name, expected in base.SOURCE_HASHES.items():
        blob = base.checked((run / "sources" / name).read_bytes(), expected)
        with (args.output / name).open("xb") as stream:
            stream.write(blob)
    for name, expected in base.FIXTURES.items():
        base.checked((run / "fixtures" / name).read_bytes(), expected)
    base.checked(args.model.read_bytes(), base.MODEL_HASH)
    far = read_pcm(run / "far_16k_reference.wav")
    if len(far) != (base.FRAMES + base.LEAD) * base.FRAME * 2:
        raise ValueError("reference_length_changed")
    base.write_wave(args.output / "far_reference.wav", far)
    for case in summary["cases"]:
        raw = read_pcm(run / case["case"] / "input.wav")
        prior = read_pcm(run / case["case"] / "processed.wav")
        base.checked(raw, case["input_pcm_sha256"])
        base.checked(prior, case["output_pcm_sha256"])
        if len(raw) != base.FRAMES * base.FRAME * 2:
            raise ValueError("case_length_changed")
        folder = args.output / case["case"]
        folder.mkdir()
        base.write_wave(folder / "input.wav", raw)
    for name, blob in (("baseline-summary.json", (run / "summary.json").read_bytes()),
                       ("baseline-config.json", (run / "config.json").read_bytes()),
                       ("baseline-harness.py", Path(base.__file__).read_bytes()),
                       ("ablation-harness.py", Path(__file__).read_bytes())):
        with (args.output / name).open("xb") as stream:
            stream.write(blob)
    base.write_json(args.output / "config.json", dict(input_scenarios=5, processing_arms=ARM_DEFINITIONS,
        treatment_outputs=20, baseline_summary_sha256=BASE_SUMMARY_HASH, baseline_config_sha256=BASE_CONFIG_HASH,
        baseline_harness_sha256=BASE_HARNESS_HASH, model_sha256=base.MODEL_HASH,
        ablation_harness_sha256=base.digest(Path(__file__).read_bytes()), settings=base.SETTINGS,
        waveform_preprocessing="reuse byte-verified frozen PCM; no new resampling, normalization or gain"))


def worker(args, base):
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", USE_TORCH="0", USE_TF="0", USE_FLAX="0",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import numpy as np
    import onnxruntime as ort
    wall, cpu = time.monotonic(), time.process_time()
    def budget():
        if time.monotonic() - wall >= args.max_seconds:
            raise TimeoutError("worker_wall_deadline")
    warnings = []
    logger = base.replay_logger(warnings)
    output = args.output
    methods = base.source_methods((output / "connection.py").read_text(encoding="utf-8"))
    selected = {arm: [] for arm in ARMS}
    functions, ast_hashes = {}, {}
    for arm in ARMS:
        node = variant(methods["_apply_aec"], arm, base)
        def capture(timestamp, aligned, target=selected[arm]):
            target.append((timestamp, aligned.astype("<i2").tobytes()))
        functions[arm] = base.compile_node(node, {"np": np, "logger": logger, "TAG": "offline-ablation",
                                                "_selected_reference": capture})
        ast_hashes[arm] = base.digest(ast.dump(node).encode())
    reset = base.compile_reset(methods["reset_audio_states"])
    tick = SimpleNamespace(milliseconds=base.BASE)
    namespace = {"np": np, "time": SimpleNamespace(time=lambda: tick.milliseconds / 1000),
                 "logger": logger, "TAG": "offline-ablation", "VADProviderBase": object}
    cls = next(item for item in ast.parse((output / "silero.py").read_text(encoding="utf-8")).body
               if isinstance(item, ast.ClassDef) and item.name == "VADProvider")
    base.compile_node(cls, namespace)
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = opts.intra_op_num_threads = 1
    base.checked(args.model.read_bytes(), base.MODEL_HASH)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"], sess_options=opts)
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("non_cpu_provider")
    class Inference:
        def __init__(self):
            self.probabilities = []
        def run(self, names, feed):
            if feed["input"].shape != (1, 576) or feed["state"].shape != (2, 1, 128) or feed["sr"].item() != 16000:
                raise ValueError("vad_feed_changed")
            values = session.run(names, feed)
            probability = float(values[0].item())
            if not np.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("invalid_vad_output")
            self.probabilities.append(probability)
            return values
    def detector():
        value = namespace["VADProvider"].__new__(namespace["VADProvider"])
        value.session = Inference()
        value.vad_threshold, value.vad_threshold_low = .5, .3
        value.silence_threshold_ms, value.frame_window_threshold = 600, 3
        return value, base.vad_connection(logger)
    def rms(pcm):
        values = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        return float(np.sqrt(np.mean(values ** 2)))
    summary = json.loads((output / "baseline-summary.json").read_text(encoding="utf-8"))
    far = read_pcm(output / "far_reference.wav")
    configs = {row[0]: row for row in base.CASES}
    results = []
    for prior in summary["cases"]:
        budget()
        name = prior["case"]
        _, has_near, has_echo, cache_enabled, offset = configs[name]
        folder = output / name
        raw = read_pcm(folder / "input.wav")
        states = {arm: detector() for arm in ARMS}
        outputs = {arm: [] for arm in ARMS}
        flags, probs, endpoints = ({arm: [] for arm in ARMS} for _ in range(3))
        trace, cache, max_window_error, edge_zero_count = [], {}, 0, 0
        conn = SimpleNamespace(aec_audio_cache=cache, logger=logger)
        for index in range(base.FRAMES):
            budget()
            tick.milliseconds = base.BASE + index * 60
            if cache_enabled:
                for j in range(max(0, index - 2), min(base.FRAMES + base.LEAD, index + base.LEAD + 1)):
                    cache[base.BASE + j * 60] = far[j * base.FRAME * 2:(j + 1) * base.FRAME * 2]
            packet = raw[index * base.FRAME * 2:(index + 1) * base.FRAME * 2]
            frame = dict(packet=index, synthetic_ms=tick.milliseconds, arms={})
            reference_control = None
            for arm in ARMS:
                selected[arm].clear()
                processed = functions[arm](conn, tick.milliseconds + offset, packet)
                if warnings or type(processed) is not bytes or len(processed) != len(packet) or len(selected[arm]) > 1:
                    raise ValueError("processing_error_dtype_or_length")
                choice = None
                if selected[arm]:
                    timestamp, reference = selected[arm][0]
                    if reference != cache[timestamp]:
                        raise ValueError("actual_reference_pair_changed")
                    choice = dict(timestamp=timestamp, frame_index=(timestamp - base.BASE) // 60,
                                  pcm_sha256=base.digest(reference), samples=len(reference) // 2)
                if arm == "original":
                    reference_control = choice
                elif choice != reference_control:
                    raise ValueError("ablation_changed_reference_selection")
                if arm == "identity" and processed != packet:
                    raise ValueError("identity_not_bit_exact")
                if arm == "hann_only":
                    expected = packet
                    if choice is not None:
                        values = np.frombuffer(packet, dtype="<i2").astype(np.float64)
                        expected = (values * np.hanning(base.FRAME)).astype("<i2").tobytes()
                        edge_zero_count += int(np.frombuffer(processed, dtype="<i2")[[0, -1]].tolist() == [0, 0])
                    error = int(np.max(np.abs(np.frombuffer(processed, dtype="<i2").astype(np.int32)
                                             - np.frombuffer(expected, dtype="<i2").astype(np.int32))))
                    max_window_error = max(max_window_error, error)
                    if error > 1:
                        raise ValueError("hann_only_not_analytic_window")
                if arm == "raw_frame_spectral_gain" and rms(processed) > rms(packet) + 1:
                    raise ValueError("candidate_energy_exceeds_input")
                provider, state = states[arm]
                provider.session.probabilities.clear()
                flag = provider.is_vad(state, processed)
                if warnings or type(flag) is not bool:
                    raise ValueError("vad_failed")
                flags[arm].append(flag)
                probs[arm].extend(provider.session.probabilities)
                if state.client_voice_stop:
                    endpoints[arm].append(index)
                    reset(state)
                outputs[arm].append(processed)
                frame["arms"][arm] = dict(vad=flag, probabilities=list(provider.session.probabilities),
                    output_pcm_sha256=base.digest(processed), output_rms=rms(processed), actual_selection=choice)
            trace.append(frame)
        metrics = {}
        for arm in ARMS:
            pcm = b"".join(outputs[arm])
            base.write_wave(folder / (arm + ".wav"), pcm)
            metrics[arm] = dict(vad_true_packets=sum(flags[arm]), inference_count=len(probs[arm]),
                probability_max=max(probs[arm]), probability_ge_high=sum(value >= .5 for value in probs[arm]),
                endpoint_packets=endpoints[arm], rms=rms(pcm), pcm_sha256=base.digest(pcm), samples=len(pcm) // 2)
        if (metrics["original"]["pcm_sha256"] != prior["output_pcm_sha256"]
                or metrics["identity"]["pcm_sha256"] != prior["input_pcm_sha256"]
                or metrics["original"]["vad_true_packets"] != prior["processed"]["vad_true_packets"]
                or metrics["identity"]["vad_true_packets"] != prior["raw"]["vad_true_packets"]):
            raise ValueError("baseline_not_reproduced")
        with (folder / "trace.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for row in trace:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        results.append(dict(case=name, has_near=has_near, has_echo=has_echo, timestamp_offset_ms=offset,
            arms=metrics, reference_selection_equal_in_all_arms=True, identity_bit_exact=True,
            original_reproduces_frozen_baseline=True, hann_only_max_abs_pcm_error=max_window_error,
            hann_only_selected_frames_with_zero_edges=edge_zero_count,
            trace_sha256=base.digest((folder / "trace.jsonl").read_bytes())))
    budget()
    if any(name == "torch" or name.startswith("torch.") for name in sys.modules):
        raise ValueError("torch_imported")
    base.write_json(output / "worker-result.json", dict(state="complete", cases=results,
        input_scenarios=len(results), processing_arms=ARM_DEFINITIONS, treatment_outputs=len(results) * len(ARMS),
        arm_ast_sha256=ast_hashes, worker_wall_seconds=time.monotonic() - wall,
        worker_cpu_seconds=time.process_time() - cpu, providers=session.get_providers(),
        numpy_version=np.__version__, onnxruntime_version=ort.__version__, warnings=len(warnings),
        torch_imported=False, owner_audio_used=False, live_requests=False,
        candidate_deployed=False, hardware_root_cause_verified=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=120)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 0 < args.max_seconds <= 120:
        parser.error("max-seconds must be in (0,120]")
    base = load_base()
    if args.worker:
        worker(args, base)
        return
    started = time.monotonic()
    deadline = started + args.max_seconds
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / "data/test-tmp").resolve()):
        parser.error("exclusive output below this worktree data/test-tmp required")
    args.output.mkdir(exist_ok=False)
    try:
        prepare(args, base)
        remaining = min(90, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("preflight_deadline")
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker",
            "--output", str(args.output), "--baseline-run", str(args.baseline_run), "--model", str(args.model),
            "--max-seconds", str(remaining)], cwd=ROOT, timeout=remaining, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        value = (json.loads((args.output / "worker-result.json").read_text(encoding="utf-8")) if result.returncode == 0
                 else dict(state="failed", failure_code="worker_failed", stderr_tail=result.stderr.decode("utf-8", errors="replace")[-1800:]))
    except subprocess.TimeoutExpired:
        value = dict(state="timeout", failure_code="parent_hard_wall_timeout")
    except Exception as error:
        value = dict(state="failed", failure_code=type(error).__name__, detail=str(error)[:300])
    value.update(parent_elapsed_seconds=time.monotonic() - started, parent_hard_wall_seconds=args.max_seconds,
                 output=str(args.output), harness_sha256=base.digest(Path(__file__).read_bytes()))
    base.write_json(args.output / "summary.json", value)
    print(json.dumps({key: value[key] for key in ("state", "output", "parent_elapsed_seconds")}))
    if value["state"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
