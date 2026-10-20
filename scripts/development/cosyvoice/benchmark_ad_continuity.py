"""AD连续性最小GPU矩阵：--run须主会话项目模型窗口收据，Windows桌面仍共享。"""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE_COMMIT = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
AG_COMMIT = "e6e8db5c82775360b920c3888a104fc0d0242938"
CASES = {
    "sentences": "下午的阳光落在窗边。我们可以先整理桌面，再慢慢安排接下来的事情。",
    "long": "如果一项任务显得复杂，可以先确认最重要的目标，再把它拆成几个能够逐步检查的小步骤，完成一步以后稍作整理，然后继续下一步。",
}


def plan():
    rows = []
    for repeat in range(3):
        for case in CASES:
            for mode in (("buffered", "adaptive") if repeat % 2 == 0 else ("adaptive", "buffered")):
                rows.append({"case": case, "mode": mode, "seed": 2710 + repeat,
                             "repeat": repeat, "segmented": True, "cancel_stage": None})
    for stage in ("before_audio", "buffering", "after_audio"):
        rows.append({"case": "long", "mode": "adaptive", "seed": 2770,
                     "repeat": 0, "segmented": False, "cancel_stage": stage})
    return {"schema_version": 1, "evidence_kind": "plan_only_no_gpu",
            "ag_capability_commit": AG_COMMIT, "engine": "existing_torch_fp16_hidden_only",
            "engine_status": "needs_isolated_validation", "new_downloads_required": False,
            "comparison": "same_candidate_buffered_vs_explicit_adaptive",
            "cache": False, "sample_rate": 24000, "rows": rows,
            "normal_calls": 12, "cancel_then_new_round_pairs": 3,
            "max_seconds": 480, "production_stop_or_restore_performed": False,
            "gpu_window_scope": "project_model_window_shared_windows_desktop", "physical_gpu_exclusive": False,
            "required_receipt_schema_version": 2,
            "physical_playback_verified": False, "full_asr_memory_llm_chain_measured": False,
            "full_chain_text_metric": "model_first_text_ms; llm_first_output_ms includes tool output"}


def validate_receipt(receipt, *, checkout, commit, production, seconds, now=None):
    """收据是外部调度证据，不会由此函数自动生成或授予GPU租约。"""
    now = now or datetime.now(timezone.utc)
    required = (type(receipt.get("schema_version")) is int and receipt.get("schema_version") == 2
        and receipt.get("scope") == "ad-cosy-project-model-window"
        and isinstance(receipt.get("window_id"), str) and bool(receipt["window_id"].strip())
        and all(receipt.get(key) is True for key in
                ("project_model_window", "production_stopped", "other_gpu_model_workers_stopped"))
        and receipt.get("physical_gpu_exclusive") is False
        and "exclusive_gpu" not in receipt
        and isinstance(receipt.get("shared_desktop_baseline"), dict)
        and receipt.get("candidate_commit") == commit
        and Path(receipt.get("checkout", "")).resolve() == checkout.resolve()
        and Path(receipt.get("production_root", "")).resolve() == production.resolve()
        and type(receipt.get("max_seconds")) is int and 60 <= seconds <= receipt["max_seconds"] <= 480)
    if not required:
        raise ValueError("matching_main_session_project_model_receipt_required")
    try:
        expires = datetime.fromisoformat(receipt["expires_at_utc"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("receipt_expiry_required") from None
    if expires.tzinfo is None or (expires - now).total_seconds() < seconds + 10:
        raise ValueError("receipt_has_insufficient_remaining_window")


def _gpu_window_module():
    spec = importlib.util.spec_from_file_location("ad_wddm_project_window", Path(__file__).with_name("gpu_window.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_gpu_idle(receipt, *, own_identity=None):
    """兼容旧内部函数名；实际只验证项目模型窗口，绝不宣称物理GPU空闲/独占。"""
    return _gpu_window_module().ensure_window(receipt, own_identity=own_identity)


def summarize(rows):
    summary = {}
    for case in CASES:
        summary[case] = {}
        for mode in ("buffered", "adaptive"):
            group = [row for row in rows if row["case"] == case and row["mode"] == mode and not row["cancel_stage"]]
            summary[case][mode] = {}
            for field in ("first_opus_ms", "first_energy_qualified_opus_ms", "total_ms", "audio_ms",
                          "estimated_playback_end_ms", "client_tts_wall_rtf",
                          "estimated_supply_gap_ms", "estimated_max_gap_ms"):
                values = [row["rounds"][0][field] for row in group if row["rounds"][0].get(field) is not None]
                summary[case][mode][field] = {"samples": len(values),
                    "median": statistics.median(values) if values else None,
                    "max": max(values) if values else None}
            values = [row["server_generation_rtf"] for row in group if row["server_generation_rtf"] is not None]
            summary[case][mode]["server_generation_rtf"] = {"samples": len(values),
                "median": statistics.median(values) if values else None, "max": max(values) if values else None}
    return summary


def worker(payload):
    # 仅父进程将本进程加入自有Job并写入管道许可后调用；不独立授权自己运行。
    output, production = Path(payload["output"]), Path(payload["production"])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    validate_receipt(payload.get("receipt", {}), checkout=ROOT, commit=commit,
                     production=production, seconds=payload["max_seconds"])
    if sys.version_info[:2] != (3, 10):
        raise RuntimeError("isolated_owner_installed_cosy_python310_required")
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode().strip()
    if dirty:
        raise ValueError("committed_clean_candidate_checkout_required")
    initial_gpu = ensure_gpu_idle(payload["receipt"])
    (output / "gpu-preflight-worker.json").write_text(json.dumps(initial_gpu, ensure_ascii=False, indent=2), encoding="utf-8")
    own_identity = _gpu_window_module().image_identity(os.getpid())
    def check_gpu(phase):
        error = None
        try:
            report = ensure_gpu_idle(payload["receipt"], own_identity=own_identity)
        except RuntimeError as caught:
            report = getattr(caught, "report", None)
            error = caught
        if report is not None:
            with (output / "gpu-window-checks.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps({"phase": phase, **report}, ensure_ascii=False) + "\n")
        if error is not None:
            raise error
        return report
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    allowed = set()
    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[:2] not in allowed:
            raise RuntimeError("worker_network_outside_owned_port")
        return connect(sock, address)
    def local_resolve(host, port, *args, **kwargs):
        if (host, port) not in allowed:
            raise RuntimeError("worker_dns_forbidden")
        return resolve(host, port, *args, **kwargs)
    socket.socket.connect, socket.getaddrinfo = local_connect, local_resolve
    import service
    from service import CosyVoiceSynthesizer, CosyVoiceHTTPServer, backend_capabilities
    def isolated_cache():
        cache = output / "runtime-cache"
        cache.mkdir()
        wetext = os.path.relpath(production / "local/runtime/modelscope-cache", ROOT)
        if os.name == "nt" and not wetext.isascii():
            raise ValueError("existing_wetext_requires_ascii_relative_path")
        os.environ.update(NUMBA_CACHE_DIR=str(cache / "numba"), MPLCONFIGDIR=str(cache / "matplotlib"),
                          HF_HOME=str(cache / "huggingface"), HF_HUB_DISABLE_TELEMETRY="1",
                          MODELSCOPE_CACHE=wetext)
        service._trial.install_modelscope_offline()
    service.configure_runtime_cache = isolated_cache
    source = production / "local/runtime/CosyVoice"
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]).decode().strip()
    if actual != SOURCE_COMMIT or dirty:
        raise ValueError("fixed_cosy_source_commit_required")
    started = time.perf_counter()
    synth = CosyVoiceSynthesizer(source, source / "pretrained_models/Fun-CosyVoice3-0.5B",
                                 profile_root=production, warm_selected_voice=False)
    load_ms = (time.perf_counter() - started) * 1000
    if not backend_capabilities(synth)["audio_stream"]["incremental_usable"]:
        raise RuntimeError("fixed_incremental_runtime_not_usable")
    selected_warmup_seconds = synth.prepare_selected_voice()
    selected_identity = synth.selected_warmup_identity
    server = CosyVoiceHTTPServer(("127.0.0.1", 0), synth)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    allowed.add(("127.0.0.1", server.server_address[1]))
    voice = production / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
    voice_python = voice / ".venv/Scripts/python.exe"
    rows, requests, active = [], [], [None]
    original_stream, original_wave = synth.stream_chunks, synth._wave_bytes
    def wave_bytes(speech):
        value = original_wave(speech)
        active[0]["last_generated_ms"] = (time.perf_counter() - active[0]["started"]) * 1000
        active[0]["audio_ms"] += speech.numel() * 1000 / synth._sample_rate
        return value
    def stream(*args, **kwargs):
        item = {"started": time.perf_counter(), "last_generated_ms": None, "audio_ms": 0}
        requests.append(item)
        active[0] = item
        try:
            yield from original_stream(*args, **kwargs)
        finally:
            item.pop("started")
    synth._wave_bytes, synth.stream_chunks = wave_bytes, stream
    try:
        for index, case in enumerate(plan()["rows"]):
            check_gpu(f"before_case_{index}")
            if synth._profiles.model_context()[2] != selected_identity:
                raise RuntimeError("selected_voice_changed_during_window")
            requests.clear()
            seed = case["seed"]
            import random
            import numpy as np
            random.seed(seed)
            np.random.seed(seed)
            synth._torch.manual_seed(seed)
            synth._torch.cuda.manual_seed_all(seed)
            synth._torch.cuda.reset_peak_memory_stats()
            config = {**case, "source_root": str(ROOT), "voice_root": str(voice),
                      "url": f"http://127.0.0.1:{server.server_address[1]}/v1/audio/stream",
                      "text": CASES[case["case"]], "cache": False, "sample_rate": 24000}
            # 原始声音只写本树忽略的独立证据目录，不写个人记忆或参考音目录。
            if not case["cancel_stage"]:
                config["audio_output"] = str(output / f"{index:02}-{case['case']}-{case['mode']}.wav")
            result = subprocess.run([str(voice_python), "-B", "-X", "utf8",
                        str(Path(__file__).with_name("benchmark_ad_client.py"))],
                        input=json.dumps(config).encode(), capture_output=True, cwd=ROOT, timeout=60,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                (output / f"client-error-{index:02}.log").write_bytes(result.stderr)
                raise RuntimeError("isolated_client_failed_see_owned_error_log")
            if server.generation_gate.locked() or synth.stream_runtime.states:
                raise RuntimeError("request_state_not_clean_after_client")
            if synth._profiles.model_context()[2] != selected_identity:
                raise RuntimeError("selected_voice_changed_during_window")
            check_gpu(f"after_case_{index}")
            audio_ms = sum(item["audio_ms"] for item in requests)
            generation_ms = sum(item["last_generated_ms"] or 0 for item in requests)
            row = {**case, **json.loads(result.stdout), "server_requests": list(requests),
                   "server_generation_rtf": None if case["cancel_stage"] or not audio_ms else generation_ms / audio_ms,
                   "rtf_scope": "server_request_to_last_pcm_includes_interchunk_transport_backpressure",
                   "peak_allocated_mib": synth._torch.cuda.max_memory_allocated() / 1048576,
                   "peak_reserved_mib": synth._torch.cuda.max_memory_reserved() / 1048576,
                   "request_cleanup": synth.stream_runtime.snapshot()}
            rows.append(row)
            with (output / "samples.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
        report = {**plan(), "evidence_kind": "isolated_real_model_tts_only",
                  "window_id": payload["window_id"], "candidate_commit": payload["candidate_commit"],
                  "source_commit": actual, "constructor_ready_ms": load_ms,
                  "selected_warmup_seconds": selected_warmup_seconds,
                  "profile_identity": selected_identity, "rows": rows,
                  "voice_scope": {"selected_uses_default_voice": synth._profiles.uses_default_voice(),
                      "measurements_after_selected_voice_warmup": True,
                      "default_reference_warmup_in_constructor": True,
                      "selected_voice_quality_verified": False},
                  "runtime": synth.runtime_info, "gpu": synth._torch.cuda.get_device_name(0),
                  "gpu_window": {"scope": "project_model_window_shared_windows_desktop",
                      "physical_gpu_exclusive": False, "background_noise_present": True,
                      "baseline_reviewed_by": payload["receipt"]["shared_desktop_baseline"]["reviewed_by"]},
                  "per_case": summarize(rows), "automatic_candidate_approved": False,
                  "owner_audio_review_required": True,
                  "duration_seconds": time.perf_counter() - started}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        serving.join(3)


def execute(args):
    production = args.production_root.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "data/test-tmp") or output.exists():
        raise ValueError("new_owned_test_output_required")
    expected_python = production / "local/runtime/CosyVoice/.venv/Scripts/python.exe"
    voice_python = production / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/.venv/Scripts/python.exe"
    if args.cosy_python.resolve() != expected_python.resolve() or not expected_python.is_file() or not voice_python.is_file():
        raise ValueError("owner_installed_separate_cosy_and_voice_interpreters_required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).decode().strip():
        raise ValueError("committed_clean_candidate_checkout_required")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_receipt(receipt, checkout=ROOT, commit=commit, production=production, seconds=args.max_seconds)
    initial_gpu = ensure_gpu_idle(receipt)
    spec = importlib.util.spec_from_file_location("ad_owned_winjob", ROOT / "scripts/development/launcher/winjob.py")
    winjob = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(winjob)
    job = winjob.Job()
    process = None
    assigned = False
    stdout = stderr = None
    try:
        output.mkdir(parents=True)
        (output / "gpu-preflight-parent.json").write_text(json.dumps(initial_gpu, ensure_ascii=False, indent=2), encoding="utf-8")
        payload = {"production": str(production), "output": str(output),
                   "window_id": receipt["window_id"], "candidate_commit": commit,
                   "receipt": receipt, "max_seconds": args.max_seconds}
        process = subprocess.Popen([str(args.cosy_python), "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        job.assign(process)
        assigned = True
        stdout, stderr = process.communicate(json.dumps(payload).encode(), timeout=args.max_seconds)
        if process.returncode:
            raise RuntimeError("owned_gpu_worker_failed")
    except subprocess.TimeoutExpired:
        (output / "deadline.json").write_text(json.dumps({"result": "owned_job_deadline_exceeded",
            "window_id": receipt["window_id"], "max_seconds": args.max_seconds}), encoding="utf-8")
        raise
    finally:
        confirmed = False
        try:
            job.close()
            confirmed = True
        finally:
            if output.is_dir():
                (output / "owned-job-cleanup.json").write_text(json.dumps({
                    "owned_job_exit_confirmed": confirmed, "window_id": receipt["window_id"],
                    "production_services_touched": False}), encoding="utf-8")
            if process is not None:
                if not assigned and process.poll() is None:
                    process.terminate()  # 仅刚创建且还在等管道许可的本进程，绝不按名称停服务。
                if stdout is None:
                    stdout, stderr = process.communicate(timeout=5)
                process.wait(timeout=5)
                (output / "worker.stdout.log").write_bytes(stdout)
                (output / "worker.stderr.log").write_bytes(stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--gpu-preflight", action="store_true", help="只读取证；不批准背景进程，不加载模型")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--cosy-python", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-seconds", type=int, default=480)
    args = parser.parse_args()
    if args.gpu_preflight and not args.run and not args.worker:
        snapshot = _gpu_window_module().collect_snapshot()
        if args.output:
            path = args.output.resolve()
            if not path.is_relative_to(ROOT / "data/test-tmp"):
                raise ValueError("owned_preflight_output_required")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as file:
                json.dump(snapshot, file, ensure_ascii=False, indent=2)
            print(json.dumps({"snapshot": str(path), "processes": len(snapshot["processes"]),
                              "physical_gpu_exclusive": False, "approval_performed": False}))
        else:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    elif args.worker:
        worker(json.loads(sys.stdin.buffer.read()))
    elif args.plan and not args.run:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
    elif args.run and not args.plan and all((args.receipt, args.production_root, args.cosy_python, args.output)):
        execute(args)
    else:
        parser.error("choose --plan, or --run with main-session receipt, production root, Cosy Python and new output")


if __name__ == "__main__":
    main()
