"""固定公开夹具的有界CPU AEC/VAD重放；不连接服务、不使用所有者声样。"""

import argparse
import ast
from collections import deque
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import wave


ROOT = Path(__file__).resolve().parents[3]
SERVER_PIN = "eb4b28c59ed7ed885258498cf757ce14352d620e"
COSY_PIN = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
SOURCE_HASHES = {
    "connection.py": "e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa",
    "silero.py": "aa375cd237c262338b391f8826f35bfe9b3c9e4c77a197bfe75490806d825114",
}
FIXTURES = {
    "zero_shot_prompt.wav": "c7b31d6dbe7cc6a716dded00550db5b50940bf209e424e4ad207b12e657c8ff6",
    "cross_lingual_prompt.wav": "353a7715c2e4811f4045658b29d1ce67ecad5120e09de10ce890f1763aab486c",
}
MODEL_HASH = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
RATE, FRAME, FRAMES, LEAD, BASE = 16000, 960, 100, 2, 1_000_000
SETTINGS = dict(sample_rate=RATE, channels=1, pcm="signed_int16_little_endian", frame_samples=FRAME,
    frame_ms=60, duration_seconds=6, reference_lead_frames=LEAD, reference_duration_seconds=6.12,
    near_start_sample=9600, common_peak_target=.8, near_gain=.45, echo_gain=.55,
    threshold=.5, threshold_low=.3, silence_ms=600, window_required=3, window_length=5,
    resample_window=["kaiser", 5.0], resample_padtype="constant")
CASES = (("near_only", True, False, False, 0), ("echo_only", False, True, True, 0),
         ("double_talk_aligned", True, True, True, 0),
         ("double_talk_timestamp_plus120ms", True, True, True, 120),
         ("near_only_unrelated_reference", True, False, True, 0))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def checked(data, expected):
    if digest(data) != expected:
        raise ValueError("fixed_source_hash_mismatch")
    return data


def source_methods(source):
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "ConnectionHandler")
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}


def instrument_selection(node):
    """只插一处只读旁路；选中实际aligned_ref后取值，不事后查最近缓存。"""
    result = copy.deepcopy(node)
    body = next(item for item in result.body if isinstance(item, ast.Try)).body
    positions = [index for index, item in enumerate(body) if isinstance(item, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "aligned_ref" for target in item.targets)]
    if len(positions) != 1 or not isinstance(body[positions[0] + 1], ast.If):
        raise ValueError("unexpected_aec_selection_shape")
    index = positions[0] + 2
    hook = ast.Expr(ast.Call(ast.Name("_selected_reference", ast.Load()),
                            [ast.Name("best_ts", ast.Load()), ast.Name("aligned_ref", ast.Load())], []))
    body.insert(index, hook)
    # 反向移除唯一插入点后，全部DSP表达式/分支必须与固定原AST一致。
    stripped = copy.deepcopy(result)
    next(item for item in stripped.body if isinstance(item, ast.Try)).body.pop(index)
    if ast.dump(stripped) != ast.dump(node):
        raise ValueError("aec_instrumentation_changed_algorithm")
    return ast.fix_missing_locations(result)


def compile_node(node, namespace):
    exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(node)], type_ignores=[])),
                 "pinned-public-replay", "exec"), namespace)
    return namespace[node.name]


def replay_logger(warnings):
    return SimpleNamespace(bind=lambda **kwargs: SimpleNamespace(debug=lambda *items: None,
        warning=lambda *items: warnings.append("aec_warning"), error=lambda *items: warnings.append("vad_error")))


def vad_connection(logger):
    return SimpleNamespace(client_listen_mode="realtime", client_audio_buffer=bytearray(),
        client_voice_window=deque(maxlen=5), last_is_voice=False, client_have_voice=False,
        client_voice_stop=False, vad_last_voice_time=0, asr_audio=[], logger=logger)


def compile_reset(node):
    return compile_node(node, {"TAG": "public-offline"})


def pcm16(values, np):
    if not np.isfinite(values).all():
        raise ValueError("nonfinite_input")
    rounded = np.rint(values)
    if rounded.min(initial=0) < -32768 or rounded.max(initial=0) > 32767:
        raise ValueError("synthetic_mix_would_clip")
    return rounded.astype("<i2")


def write_wave(path, pcm):
    with path.open("xb") as stream:
        with wave.open(stream, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm)


def prepare(args, output, deadline):
    sources, fixtures = output / "sources", output / "fixtures"
    sources.mkdir()
    fixtures.mkdir()
    def git(repo, *command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("run_deadline")
        return subprocess.check_output(["git", "-C", str(repo), *command], cwd=ROOT,
            timeout=min(8, remaining), stderr=subprocess.PIPE)
    for repo, pin in ((args.server_repo, SERVER_PIN), (args.cosy_repo, COSY_PIN)):
        if git(repo, "rev-parse", "HEAD").decode().strip() != pin:
            raise ValueError("vendor_head_mismatch")
    for name, relative in (("connection.py", "main/xiaozhi-server/core/connection.py"),
                           ("silero.py", "main/xiaozhi-server/core/providers/vad/silero.py")):
        blob = checked(git(args.server_repo, "show", SERVER_PIN + ":" + relative), SOURCE_HASHES[name])
        if (args.server_repo / relative).read_bytes() != blob:
            raise ValueError("vendor_source_disk_differs_from_pin")
        with (sources / name).open("xb") as stream:
            stream.write(blob)
    for name, expected in FIXTURES.items():
        blob = checked(git(args.cosy_repo, "show", COSY_PIN + ":asset/" + name), expected)
        if (args.cosy_repo / "asset" / name).read_bytes() != blob:
            raise ValueError("public_fixture_disk_differs_from_pin")
        with (fixtures / name).open("xb") as stream:
            stream.write(blob)
    checked(args.model.read_bytes(), MODEL_HASH)
    with (sources / "harness.py").open("xb") as stream:
        stream.write(Path(__file__).read_bytes())
    write_json(output / "config.json", dict(settings=SETTINGS, cases=CASES,
        server_pin=SERVER_PIN, cosy_pin=COSY_PIN, fixture_sha256=FIXTURES, source_sha256=SOURCE_HASHES,
        model_sha256=MODEL_HASH, harness_sha256=digest(Path(__file__).read_bytes())))


def worker(args):
    # 在导入任何科学计算库前约束CPU/离线，绝不导入应用提供器/torch。
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", USE_TORCH="0", USE_TF="0", USE_FLAX="0",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import numpy as np
    import scipy
    from scipy.signal import resample_poly
    import soundfile as sf
    import onnxruntime as ort
    wall, cpu = time.monotonic(), time.process_time()
    def budget():
        if time.monotonic() - wall >= args.max_seconds or time.process_time() - cpu >= args.max_seconds:
            raise TimeoutError("worker_wall_or_cpu_budget")
    output = args.output
    warnings = []
    logger = replay_logger(warnings)
    methods = source_methods((output / "sources/connection.py").read_text(encoding="utf-8"))
    selected = []
    def selection(timestamp, aligned):
        selected.append((timestamp, aligned.astype("<i2").tobytes()))
    original = compile_node(methods["_apply_aec"], {"np": np, "TAG": "public-offline", "logger": logger})
    observed = compile_node(instrument_selection(methods["_apply_aec"]),
                            {"np": np, "TAG": "public-offline", "logger": logger, "_selected_reference": selection})
    reset = compile_reset(methods["reset_audio_states"])
    ticks = SimpleNamespace(milliseconds=BASE)
    namespace = {"np": np, "time": SimpleNamespace(time=lambda: ticks.milliseconds / 1000),
                 "logger": logger, "TAG": "public-offline", "VADProviderBase": object}
    vad_cls = next(item for item in ast.parse((output / "sources/silero.py").read_text(encoding="utf-8")).body
                   if isinstance(item, ast.ClassDef) and item.name == "VADProvider")
    compile_node(vad_cls, namespace)
    options = ort.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    checked(args.model.read_bytes(), MODEL_HASH)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"], sess_options=options)
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("unexpected_execution_provider")
    decoded, metadata = [], []
    for name, up, down in (("zero_shot_prompt.wav", 2, 3), ("cross_lingual_prompt.wav", 320, 441)):
        path = output / "fixtures" / name
        info = sf.info(str(path))
        values, rate = sf.read(str(path), dtype="float64", always_2d=False)
        if info.channels != 1 or rate != (24000 if up == 2 else 22050):
            raise ValueError("fixture_format_changed")
        values = resample_poly(values, up, down, window=("kaiser", 5.0), padtype="constant")
        decoded.append(values)
        metadata.append(dict(name=name, sha256=digest(path.read_bytes()), original_rate=rate,
            channels=info.channels, subtype=info.subtype, original_frames=info.frames,
            resample_up=up, resample_down=down, resampled_frames=len(values)))
    scale = SETTINGS["common_peak_target"] / max(float(np.max(np.abs(values))) for values in decoded)
    near_source = pcm16(decoded[0] * scale * 32767, np)
    far = pcm16(decoded[1][: (FRAMES + LEAD) * FRAME] * scale * 32767, np)
    if len(far) != (FRAMES + LEAD) * FRAME or len(near_source) + SETTINGS["near_start_sample"] > FRAMES * FRAME:
        raise ValueError("fixture_too_short_or_long")
    near = np.zeros(FRAMES * FRAME, dtype=np.int16)
    near_start = SETTINGS["near_start_sample"]
    near[near_start:near_start + len(near_source)] = near_source
    write_wave(output / "near_16k_timeline.wav", near.tobytes())
    write_wave(output / "far_16k_reference.wav", far.tobytes())

    class Inference:
        def __init__(self):
            self.probabilities = []
        def run(self, names, feed):
            if feed["input"].shape != (1, 576) or feed["state"].shape != (2, 1, 128) or feed["sr"].item() != RATE:
                raise ValueError("vad_input_contract")
            result = session.run(names, feed)
            probability = float(result[0].item())
            if not np.isfinite(probability) or not 0 <= probability <= 1:
                raise ValueError("invalid_vad_probability")
            self.probabilities.append(probability)
            return result
    def detector():
        value = namespace["VADProvider"].__new__(namespace["VADProvider"])
        value.session = Inference()
        value.vad_threshold, value.vad_threshold_low = .5, .3
        value.silence_threshold_ms, value.frame_window_threshold = 600, 3
        conn = vad_connection(logger)
        return value, conn
    def rms(values):
        return round(float(np.sqrt(np.mean(values.astype(np.float64) ** 2))), 6)
    cases = []
    for name, has_near, has_echo, cache_enabled, offset in CASES:
        budget()
        case = output / name
        case.mkdir()
        raw = pcm16((SETTINGS["near_gain"] * near.astype(np.float64) if has_near else 0)
                    + (SETTINGS["echo_gain"] * far[:FRAMES * FRAME].astype(np.float64) if has_echo else 0), np)
        raw_detector, raw_conn = detector()
        out_detector, out_conn = detector()
        raw_flags, out_flags, endpoints, outputs, rows = [], [], [[], []], [], []
        cache = {}
        aec_conn = SimpleNamespace(aec_audio_cache=cache, logger=logger)
        for index in range(FRAMES):
            budget()
            ticks.milliseconds = BASE + index * 60
            if cache_enabled:
                for reference_index in range(max(0, index - 2), min(FRAMES + LEAD, index + LEAD + 1)):
                    cache[BASE + reference_index * 60] = far[reference_index * FRAME:(reference_index + 1) * FRAME].tobytes()
            packet = raw[index * FRAME:(index + 1) * FRAME].tobytes()
            selected.clear()
            before = original(aec_conn, ticks.milliseconds + offset, packet)
            if warnings:
                raise ValueError("upstream_aec_warning_stop")
            after = observed(aec_conn, ticks.milliseconds + offset, packet)
            if before != after or warnings or len(selected) > 1:
                raise ValueError("aec_transparency_or_upstream_error")
            choice = None
            if selected:
                chosen_ts, reference = selected[0]
                if reference != cache[chosen_ts] or len(reference) != FRAME * 2:
                    raise ValueError("selected_reference_not_actual_cache_slice")
                chosen_index = (chosen_ts - BASE) // 60
                choice = dict(timestamp=chosen_ts, frame_index=chosen_index, pcm_sha256=digest(reference),
                              samples=len(reference) // 2, offset_from_known_echo_frames=chosen_index - index)
            flags, probabilities = [], []
            for branch, (provider, conn, data) in enumerate(((raw_detector, raw_conn, packet), (out_detector, out_conn, after))):
                provider.session.probabilities.clear()
                flag = provider.is_vad(conn, data)
                if type(flag) is not bool or warnings:
                    raise ValueError("upstream_vad_error_or_unknown")
                flags.append(flag)
                probabilities.append(list(provider.session.probabilities))
                if conn.client_voice_stop:
                    endpoints[branch].append(index)
                    reset(conn)  # 固定上游reset；保留其原有RNN/context生命周期。
            raw_flags.append(flags[0])
            out_flags.append(flags[1])
            outputs.append(after)
            rows.append(dict(packet=index, synthetic_ms=ticks.milliseconds, input_timestamp=ticks.milliseconds + offset,
                near_source_coverage=near_start <= index * FRAME < near_start + len(near_source),
                known_echo_reference_frame=index if has_echo else None, actual_selection=choice,
                before_rms=rms(np.frombuffer(packet, dtype="<i2")), after_rms=rms(np.frombuffer(after, dtype="<i2")),
                raw_vad=flags[0], processed_vad=flags[1], raw_probabilities=probabilities[0],
                processed_probabilities=probabilities[1], original_equals_instrumented=True))
        processed = b"".join(outputs)
        if name == "near_only" and (processed != raw.tobytes() or raw_flags != out_flags or not any(raw_flags)):
            raise ValueError("near_positive_control_or_transparency_failed")
        write_wave(case / "input.wav", raw.tobytes())
        write_wave(case / "processed.wav", processed)
        with (case / "trace.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        def branch_stats(key, flags):
            probabilities = [value for row in rows for value in row[key]]
            covered = [i for i, row in enumerate(rows) if row["near_source_coverage"]]
            return dict(vad_true_packets=sum(flags), near_source_coverage_true_packets=sum(flags[i] for i in covered),
                inference_count=len(probabilities), probability_max=max(probabilities),
                probability_ge_high=sum(value >= .5 for value in probabilities))
        selections = [row["actual_selection"] for row in rows if row["actual_selection"] is not None]
        histogram = {}
        for selection_row in selections:
            key = str(selection_row["offset_from_known_echo_frames"])
            histogram[key] = histogram.get(key, 0) + 1
        cases.append(dict(case=name, has_near=has_near, has_echo=has_echo, cache_enabled=cache_enabled,
            timestamp_offset_ms=offset, input_pcm_sha256=digest(raw.tobytes()), output_pcm_sha256=digest(processed),
            input_rms=rms(raw), output_rms=rms(np.frombuffer(processed, dtype="<i2")),
            raw=branch_stats("raw_probabilities", raw_flags), processed=branch_stats("processed_probabilities", out_flags),
            raw_endpoint_packets=endpoints[0], processed_endpoint_packets=endpoints[1],
            selected_reference_calls=len(selections), selected_offset_frames_histogram=histogram,
            actual_reference_hashes_verified=True, aec_original_and_instrumented_equal=True,
            trace_path=name + "/trace.jsonl", trace_sha256=digest((case / "trace.jsonl").read_bytes())))
    budget()
    if any(name == "torch" or name.startswith("torch.") for name in sys.modules):
        raise ValueError("torch_imported")
    result = dict(state="complete", fixtures=metadata, common_source_scale=scale, cases=cases,
        numpy_version=np.__version__, scipy_version=scipy.__version__, soundfile_version=sf.__version__,
        onnxruntime_version=ort.__version__, providers=session.get_providers(),
        worker_wall_seconds=round(time.monotonic() - wall, 6), worker_cpu_seconds=round(time.process_time() - cpu, 6),
        torch_imported=False, gpu_used=False, live_service_requests=False, owner_audio_used=False,
        upstream_warnings=len(warnings), opus_roundtrip_executed=False,
        vad_clock="synthetic_exact_60ms_delivery", hardware_or_owner_root_cause_verified=False)
    write_json(output / "worker-result.json", result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--server-repo", type=Path)
    parser.add_argument("--cosy-repo", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-seconds", type=float, default=120)
    args = parser.parse_args(argv)
    if not 0 < args.max_seconds <= 120:
        parser.error("max-seconds must be in (0,120]")
    if args.worker:
        worker(args)
        return
    started = time.monotonic()
    deadline = started + args.max_seconds
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / "data/test-tmp").resolve()) or not args.server_repo or not args.cosy_repo:
        parser.error("exclusive output below this worktree data/test-tmp and explicit vendor roots required")
    args.output.mkdir(exist_ok=False)
    result = {}
    try:
        prepare(args, args.output, deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("preflight_deadline")
        command = [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker",
                   "--output", str(args.output), "--model", str(args.model), "--max-seconds", str(min(90, remaining))]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=min(90, remaining),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode:
            result = dict(state="failed", failure_code="worker_failed", returncode=completed.returncode,
                          stderr_tail=completed.stderr.decode("utf-8", errors="replace")[-1800:])
        else:
            result = json.loads((args.output / "worker-result.json").read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        result = dict(state="timeout", failure_code="hard_subprocess_timeout")
    except Exception as error:
        result = dict(state="failed", failure_code=type(error).__name__, detail=str(error)[:300])
    result.update(run_hard_wall_limit_seconds=args.max_seconds,
                  parent_elapsed_seconds=round(time.monotonic() - started, 6),
                  harness_sha256=digest(Path(__file__).read_bytes()), output=str(args.output))
    write_json(args.output / "summary.json", result)
    print(json.dumps({key: result[key] for key in ("state", "output", "parent_elapsed_seconds")}))
    if result["state"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
