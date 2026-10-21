"""AD 三模式短句诊断；默认仅计划。--run 只连接另行准备的单实例，不管理服务。"""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import http.client
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = "127.0.0.1", 18774
URL = f"http://{HOST}:{PORT}/v1/audio/stream"
SOURCE_COMMIT = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
TEXTS = ("下午的阳光落在窗边。", "我们可以先整理桌面，再慢慢安排接下来的事情。")
MODES = ("buffered", "incremental", "adaptive")
RATE, FRAME_SAMPLES = 24000, 1440
MAX_SECONDS, REQUEST_SECONDS, MAX_CALLS = 300, 15, 16


def plan():
    rows = []
    for repeat in range(2):
        for text_id in range(2):
            for mode in MODES if repeat == 0 else reversed(MODES):
                rows.append(dict(kind="measurement", repeat=repeat, text_id=text_id, mode=mode))
    rows.extend((dict(kind="cancel_after_energy", text_id=1, mode="adaptive"),
                 dict(kind="reuse", text_id=0, mode="adaptive")))
    return dict(schema_version=1, evidence_kind="plan_only_no_network_no_model",
                url=URL, texts=list(TEXTS), rows=rows, cache=False,
                measured_calls=12, cancel_calls=1, reuse_calls=1,
                external_startup_warmup_calls_max=2, max_total_synthesis_calls=MAX_CALLS,
                max_seconds=MAX_SECONDS, request_seconds=REQUEST_SECONDS,
                seed_control="unavailable_in_existing_http_api",
                comparison="same_text_forward_reverse_order_unseeded_two_repeats",
                startup_and_warmup_included_in_receipt_window=True,
                launches_or_stops_services=False, automatic_mode_selection=False,
                physical_playback_verified=False,
                energy_gate=dict(window_ms=5, pcm16_rms_threshold=200,
                                 minimum_fraction_abs_at_least_threshold=.5,
                                 definition="rolling_rms_and_sustained_sample_occupancy"))


def validate_url(url):
    # 不接受别名、重定向、用户信息或参数，防止误连日用端口。
    if url != URL:
        raise ValueError("only_fixed_isolated_127_0_0_1_18774_allowed")


def validate_receipt(receipt, commit, *, now=None):
    now = now or datetime.now(timezone.utc)
    if (receipt.get("schema_version") != 1
            or receipt.get("scope") != "ad-three-mode-external-single-instance"
            or receipt.get("reviewed_by") != "main_session"
            or receipt.get("candidate_commit") != commit
            or Path(receipt.get("checkout", "")).resolve() != ROOT
            or receipt.get("url") != URL
            or not isinstance(receipt.get("window_id"), str) or not receipt["window_id"].strip()
            or any(receipt.get(key) is not True for key in (
                "production_stopped", "other_gpu_model_workers_stopped", "single_model_instance",
                "service_source_matches_candidate", "source_and_model_verified",
                "external_service_startup_warmups_within_15s_each"))
            or type(receipt.get("external_warmup_calls")) is not int
            or not 1 <= receipt["external_warmup_calls"] <= 2
            or receipt.get("max_seconds") != MAX_SECONDS
            or receipt.get("physical_gpu_exclusive") is not False
            or not isinstance(receipt.get("shared_desktop_baseline"), dict)
            or not isinstance(receipt.get("service_identity"), dict)):
        raise ValueError("new_matching_main_session_resource_receipt_required")
    identity = receipt["service_identity"]
    if (type(identity.get("pid")) is not int or identity["pid"] <= 0
            or not identity.get("creation_token") or not identity.get("executable_path")):
        raise ValueError("external_service_image_identity_required")
    try:
        started = datetime.fromisoformat(receipt["started_at_utc"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(receipt["expires_at_utc"].replace("Z", "+00:00"))
        if started.tzinfo is None or expires.tzinfo is None:
            raise ValueError()
        age = (now - started).total_seconds()
        remaining = min(MAX_SECONDS - age, (expires - now).total_seconds())
    except (KeyError, TypeError, ValueError):
        raise ValueError("bounded_timezone_aware_resource_window_required") from None
    if not 0 <= age < MAX_SECONDS or remaining <= 0:
        raise ValueError("resource_window_expired_or_future")
    return remaining


class StopRun(RuntimeError):
    pass


class Cancelled(StopRun):
    pass


@contextmanager
def fixed_network():
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[:2] != (HOST, PORT):
            raise StopRun("network_outside_fixed_port")
        return connect(sock, address)
    def local_resolve(host, port, *args, **kwargs):
        if (host, port) != (HOST, PORT):
            raise StopRun("dns_outside_fixed_port")
        return resolve(host, port, *args, **kwargs)
    socket.socket.connect, socket.getaddrinfo = local_connect, local_resolve
    try:
        yield
    finally:
        socket.socket.connect, socket.getaddrinfo = connect, resolve


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise StopRun("deadline_exceeded")
    return value


def health(deadline):
    connection = http.client.HTTPConnection(HOST, PORT, timeout=min(2, remaining(deadline)))
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 1024 * 1024:
            raise StopRun("health_rejected_or_oversize")
        return json.loads(raw)
    finally:
        connection.close()


def check_health(value, expected_identity=None, *, require_idle=True):
    stream = value.get("capabilities", {}).get("audio_stream", {})
    identity = stream.get("profile_identity", {})
    guard = value.get("stream_runtime", {})
    runtime = value.get("runtime", {})
    warmups = (value.get("warmup_seconds"), value.get("selected_voice_warmup_seconds"))
    if (value.get("ready") is not True or value.get("requires_restart") is not False
            or stream.get("incremental_usable") is not True or stream.get("force_buffered") is not False
            or guard.get("applied") is not True
            or identity.get("state") != "valid" or identity.get("selected_voice_warm") is not True
            or value.get("selected_voice_warm") is not True
            or not isinstance(identity.get("context_digest"), str)
            or not isinstance(identity.get("config_digest"), str)
            or runtime.get("fp16") is not True or runtime.get("hidden_only") is not True
            or any(type(seconds) not in (int, float) or not 0 <= seconds <= REQUEST_SECONDS for seconds in warmups)):
        raise StopRun("ready_warm_incremental_fixed_runtime_required")
    selected = (identity["config_digest"], identity["context_digest"])
    if expected_identity is not None and selected != expected_identity:
        raise StopRun("selected_profile_changed")
    if require_idle and (value.get("generation_in_flight") is not False or guard.get("active_requests") != 0):
        raise StopRun("server_not_idle")
    return selected


def idle_health(deadline, identity):
    began = time.perf_counter()
    while True:
        value = health(deadline)
        check_health(value, identity, require_idle=False)
        if value.get("generation_in_flight") is False and value["stream_runtime"].get("active_requests") == 0:
            return value, (time.perf_counter() - began) * 1000
        time.sleep(min(.02, remaining(deadline)))


def diagnostic_delta(before, after):
    output = {}
    for stage in ("llm_job", "flow", "hift", "text_normalize"):
        first, last = before.get(stage), after.get(stage)
        if not isinstance(first, dict) or not isinstance(last, dict):
            output[stage] = None
            continue
        calls, wall = last["calls"] - first["calls"], last["wall_ms"] - first["wall_ms"]
        if calls < 0 or wall < -.001:
            raise StopRun("diagnostic_counters_reset")
        output[stage] = {"calls": calls, "wall_ms": round(max(0, wall), 3)}
    return output


class EnergyGate:
    """连续5ms窗口RMS≥200且至少一半样本|幅值|≥200；跨帧保留窗口。

    200/32768约为-44.3 dBFS。附加50%占有率排除单个满幅尖峰撑高RMS；
    正常过零可保留，静音/单峰不能冒充持续声音。这仍不是首字或听感检测。
    """
    def __init__(self):
        self.samples = deque()
        self.sum_squares = 0
        self.above_threshold = 0
        self.qualified = False

    def feed(self, pcm):
        if len(pcm) % 2:
            raise StopRun("unaligned_decoded_pcm")
        for (value,) in struct.iter_unpack("<h", pcm):
            self.samples.append(value)
            self.sum_squares += value * value
            self.above_threshold += abs(value) >= 200
            window = RATE // 200
            if len(self.samples) > window:
                old = self.samples.popleft()
                self.sum_squares -= old * old
                self.above_threshold -= abs(old) >= 200
            if (len(self.samples) == window and self.sum_squares >= window * 200 ** 2
                    and self.above_threshold * 2 >= window):
                self.qualified = True
        return self.qualified


def run_case(case, consumer, encoder, decoder, deadline):
    """仅复用当前PCM/缓冲/Opus策略；文字已就绪，不伪造LLM或设备指标。"""
    started = time.perf_counter()
    row = dict(case, first_pcm_ms=None, first_opus_ms=None, first_energy_opus_ms=None,
               pcm_samples=0, opus_frames=0, decoded_samples=0, wav_chunks=0, eos=False,
               cancel_triggered=False, packets_after_cancel=0, outcome="incomplete")
    gate = EnergyGate()
    timeline = consumer.PlaybackTimeline()
    stopped = threading.Event()
    wire = {"socket": None}
    def cancel():
        return stopped.is_set() or time.monotonic() >= deadline
    def ms():
        return (time.perf_counter() - started) * 1000
    def watchdog():
        while not stopped.wait(.01):
            if time.monotonic() >= deadline:
                break
        sock = wire["socket"]
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    watch = threading.Thread(target=watchdog, name="ad-three-mode-owned-socket", daemon=True)
    watch.start()
    buffer = None
    pieces = None
    def source(is_cancelled):
        connection = http.client.HTTPConnection(HOST, PORT, timeout=min(2, remaining(deadline)))
        response = None
        try:
            connection.connect()
            wire["socket"] = connection.sock
            connection.sock.settimeout(remaining(deadline))
            body = dict(input=TEXTS[case["text_id"]], response_format="wav", stream=True,
                        cache=False, delivery_mode="buffered" if case["mode"] == "buffered" else "incremental")
            connection.request("POST", "/v1/audio/stream", json.dumps(body).encode("utf-8"),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            if (response.status != 200
                    or response.headers.get("Content-Type") != "application/vnd.longmemory.wav-chunks"
                    or response.headers.get("X-LongMemory-Audio-Stream") != "2"):
                raise StopRun("stream_rejected_no_retry_no_fallback")
            pcm = consumer.ContinuousPCM(RATE)
            for wav in consumer.iter_wav_chunks(response, require_end=True):
                if is_cancelled():
                    raise Cancelled("cancelled_or_deadline")
                data = pcm.feed(wav)
                row["wav_chunks"] += 1
                row["pcm_samples"] += len(data) // 2
                if row["pcm_samples"] > RATE * 60 or row["wav_chunks"] > 1000:
                    raise StopRun("audio_budget_exceeded")
                if data and row["first_pcm_ms"] is None:
                    row["first_pcm_ms"] = ms()
                if data:
                    yield data
            if response.read(1):
                raise StopRun("trailing_bytes_after_eos")
            row["eos"] = True
            tail = pcm.finish()
            if tail:
                row["pcm_samples"] += len(tail) // 2
                yield tail
        finally:
            if response is not None:
                response.close()
            connection.close()
            wire["socket"] = None
    def deliver(packet):
        if row["cancel_triggered"]:
            row["packets_after_cancel"] += 1
            raise Cancelled("packet_after_cancel")
        remaining(deadline)
        at = ms()
        decoded = decoder.decode(packet, FRAME_SAMPLES)
        if len(decoded) != FRAME_SAMPLES * 2:
            raise StopRun("decoded_frame_size_invalid")
        row["opus_frames"] += 1
        row["decoded_samples"] += len(decoded) // 2
        if row["first_opus_ms"] is None:
            row["first_opus_ms"] = at
        timeline.packet()
        if gate.feed(decoded) and row["first_energy_opus_ms"] is None:
            row["first_energy_opus_ms"] = ms()
            if case["kind"] == "cancel_after_energy":
                # 短句可能已生成完才播放；这种情况不能冒充取消了真实在途模型工作。
                live = health(deadline)
                row["cancel_live_work_observed"] = (live.get("generation_in_flight") is True
                    and live.get("stream_runtime", {}).get("active_requests", 0) > 0)
                if not row["cancel_live_work_observed"]:
                    raise StopRun("energy_boundary_after_generation_completed_no_cancel_proof")
                row["cancel_triggered"] = True
                row["cancel_at_ms"] = ms()
                stopped.set()
                raise Cancelled("intentional_after_energy")
    encoder.reset_state()
    try:
        if case["mode"] == "adaptive":
            buffer = consumer.AdaptivePCMBuffer(source, RATE, cancel, timeline)
            pieces = iter(buffer)
        else:
            pieces = source(cancel)
        collected = []
        for pcm in pieces:
            remaining(deadline)
            if case["mode"] == "buffered":
                collected.append(pcm)
            else:
                encoder.encode_pcm_to_opus_stream(pcm, end_of_stream=False, callback=deliver)
        encoder.encode_pcm_to_opus_stream(b"".join(collected), end_of_stream=True, callback=deliver)
        if case["kind"] == "cancel_after_energy":
            raise StopRun("energy_cancel_boundary_not_reached")
        if (not row["eos"] or row["first_energy_opus_ms"] is None
                or row["opus_frames"] != math.ceil(row["pcm_samples"] / FRAME_SAMPLES)):
            raise StopRun("empty_silent_or_incomplete_audio")
        row["outcome"] = "complete"
    except (Cancelled, consumer._SpeechCancelled):
        if not row["cancel_triggered"]:
            raise StopRun("unexpected_cancel_or_deadline") from None
        row["outcome"] = "intentional_cancel"
    finally:
        stopped.set()
        try:
            if pieces is not None:
                pieces.close()
        finally:
            try:
                if buffer is not None:
                    buffer.close()
            finally:
                encoder.reset_state()
                watch.join(timeout=.2)
    remaining(deadline)
    row.update(client_total_ms=ms(), audio_ms=row["pcm_samples"] * 1000 / RATE,
               tail_padding_samples=(row["decoded_samples"] - row["pcm_samples"]
                                     if row["outcome"] == "complete" else None),
               estimated_supply=timeline.snapshot(), owned_socket_watcher_stopped=not watch.is_alive())
    if buffer is not None:
        row["adaptive_buffer"] = buffer.snapshot()
    if row["cancel_triggered"]:
        row["cancel_to_client_return_ms"] = ms() - row["cancel_at_ms"]
    if watch.is_alive() or row.get("adaptive_buffer", {}).get("reader_stopped") is False:
        raise StopRun("client_reader_not_stopped")
    return row


def matrix(consumer, encoder, decoder_factory, deadline, warmups, emit, resource_check):
    resource_check()
    before = health(deadline)
    identity = check_health(before)
    service_digest = hashlib.sha256((ROOT / "scripts/development/cosyvoice/service.py").read_bytes()).hexdigest()
    if before.get("runtime", {}).get("service_sha256") != service_digest:
        raise StopRun("service_source_hash_mismatch")
    completed = []
    # 不保存健康响应正文/声线摘要，身份只在内存比较。
    for index, case in enumerate(plan()["rows"]):
        resource_check()
        emit(dict(event="operation_begin", index=index, kind=case["kind"]))
        began = time.perf_counter()
        call_deadline = min(deadline, time.monotonic() + REQUEST_SECONDS)
        before = health(call_deadline)
        check_health(before, identity)
        row = run_case(case, consumer, encoder, decoder_factory(), call_deadline)
        after, cleanup_ms = idle_health(call_deadline, identity)
        if after.get("runtime", {}).get("service_sha256") != service_digest:
            raise StopRun("service_instance_implementation_changed")
        row.update(index=index, server_idle_after=True, server_cleanup_wait_ms=cleanup_ms,
                   operation_total_ms=(time.perf_counter() - began) * 1000,
                   diagnostic_delta=diagnostic_delta(before.get("diagnostics", {}), after.get("diagnostics", {})),
                   voice_identity_unchanged=True)
        completed.append(row)
        emit(dict(event="operation_complete", row=row))
    return dict(event="complete", evidence_kind="isolated_tts_transport_no_device",
                calls_including_external_warmups=len(completed) + warmups,
                rows_completed=len(completed), seed_control="unavailable_in_existing_http_api",
                diagnostic_stage_times_additive=False, automatic_candidate_approved=False,
                physical_playback_verified=False, owner_audio_review_required=True)


def load_cpu(voice_root):
    """只加载所有者已有CPU编码器；不导入服务、torch、模型或完整上游应用。"""
    sys.path[:0] = [str(ROOT / "scripts/development/xiaozhi"), str(voice_root)]
    native = voice_root / "native/libopus-1.6.1/Library/bin"
    os.environ["PATH"] = str(native) + os.pathsep + os.environ.get("PATH", "")
    dll = os.add_dll_directory(str(native))
    try:
        import cosyvoice_streaming as consumer
        from core.utils.opus_encoder_utils import OpusEncoderUtils
        from opuslib_next import Decoder
        if Path(consumer.__file__).resolve() != ROOT / "scripts/development/xiaozhi/cosyvoice_streaming.py":
            raise StopRun("consumer_source_tree_mismatch")
        encoder = OpusEncoderUtils(RATE, 1, 60)
        return consumer, encoder, lambda: Decoder(RATE, 1), dll
    except BaseException:
        dll.close()
        raise


def gpu_guard(receipt):
    spec = importlib.util.spec_from_file_location("ad_three_mode_gpu_window", Path(__file__).with_name("gpu_window.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 收据中的模型PID还必须实际拥有该固定监听端口；仅命中同一台GPU不够。
    script = "@(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18774 -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique) | ConvertTo-Json -Compress"
    raw = subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                  timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    owner = json.loads(raw.decode("utf-8-sig"))
    if owner != receipt["service_identity"]["pid"]:
        raise StopRun("fixed_listener_not_owned_by_receipt_service")
    report = module.ensure_window(receipt, own_identity=receipt["service_identity"])
    # 只把分类/计数写入事件，不保存进程路径或原始系统清单。
    if not any(item["classification"] == "owned_benchmark_model" for item in report["approved"]):
        raise StopRun("external_service_not_observed_as_single_model")


def worker(payload):
    receipt = payload["receipt"]
    seconds = validate_receipt(receipt, payload["commit"])
    emit = lambda value: print(json.dumps(value, ensure_ascii=False), flush=True)
    consumer = encoder = dll = None
    deadline = time.monotonic() + seconds
    try:
        with fixed_network():
            gpu_guard(receipt)
            consumer, encoder, decoder, dll = load_cpu(Path(payload["voice_root"]))
            emit(matrix(consumer, encoder, decoder, deadline, receipt["external_warmup_calls"],
                        emit, lambda: gpu_guard(receipt)))
    except Exception as error:
        # 不复制异常正文：外部库的异常可能包含档案路径或响应正文。
        reason = str(error) if type(error) is StopRun else "worker_stopped_no_retry"
        emit(dict(event="failed", reason=reason, server_cleanup_unconfirmed=True))
        return 1
    finally:
        if encoder is not None:
            encoder.close()
        if dll is not None:
            dll.close()
    return 0


def supervise(process, deadline, emit, *, clock=time.monotonic):
    """父进程硬限时仅终止自有CPU子进程；不杀外部服务，失败需所有者核查GPU清理。"""
    messages = queue.Queue()
    def read():
        for line in process.stdout:
            messages.put(line)
        messages.put(None)
    reader = threading.Thread(target=read, name="ad-three-mode-events", daemon=True)
    reader.start()
    operation_deadline = deadline
    complete = False
    active, next_index = None, 0
    expected = plan()["rows"]
    try:
        while True:
            left = min(deadline, operation_deadline) - clock()
            if left <= 0:
                raise StopRun("parent_wall_or_request_deadline_exceeded")
            try:
                line = messages.get(timeout=min(.05, left))
            except queue.Empty:
                continue
            if line is None:
                break
            if len(line) > 65536:
                raise StopRun("worker_event_oversize")
            value = json.loads(line)
            kind = value.get("event")
            if kind == "operation_begin":
                if (complete or active is not None or next_index >= len(expected)
                        or value.get("index") != next_index or value.get("kind") != expected[next_index]["kind"]):
                    raise StopRun("worker_operation_order_invalid")
                active = next_index
                operation_deadline = min(deadline, clock() + REQUEST_SECONDS)
            elif kind == "operation_complete":
                row = value.get("row", {})
                if active is None or row.get("index") != active or row.get("server_idle_after") is not True:
                    raise StopRun("worker_completion_without_idle_or_matching_operation")
                active, next_index = None, next_index + 1
                operation_deadline = deadline
            elif kind == "complete":
                if (complete or active is not None or next_index != len(expected)
                        or value.get("rows_completed") != len(expected)
                        or not len(expected) + 1 <= value.get("calls_including_external_warmups", 0) <= MAX_CALLS):
                    raise StopRun("worker_incomplete_matrix_or_call_budget")
                complete = True
            elif kind != "failed":
                raise StopRun("worker_event_invalid")
            emit(value)
        process.wait(timeout=max(.001, min(1, deadline - clock())))
        if process.returncode or not complete:
            raise StopRun("worker_incomplete")
    finally:
        if process.poll() is None:
            process.kill()  # Popen刚创建的CPU客户端；绝不按PID收据终止模型服务。
        process.wait(timeout=2)
        reader.join(timeout=.2)


def execute(args):
    validate_url(args.url)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("committed_clean_candidate_required")
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    seconds = validate_receipt(receipt, commit)
    production = args.production_root.resolve()
    voice = production / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
    python = voice / ".venv/Scripts/python.exe"
    source = production / "local/runtime/CosyVoice"
    if not python.is_file():
        raise ValueError("owner_installed_voice_cpu_python_required")
    if (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() != SOURCE_COMMIT
            or subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True).strip()):
        raise ValueError("fixed_clean_external_source_required")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "experiments/results") or output.exists():
        raise ValueError("new_owned_experiments_results_directory_required")
    output.mkdir(parents=True)
    payload = dict(receipt=receipt, commit=commit, voice_root=str(voice))
    # 无继承PYTHONPATH/用户启动脚本。只允许此子进程已有编码器路径。
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONSTARTUP"}}
    with (output / "summary.jsonl").open("x", encoding="utf-8") as file:
        def emit(value):
            file.write(json.dumps(value, ensure_ascii=False) + "\n")
            file.flush()
        emit(dict(event="start", candidate_commit=commit, source_commit=SOURCE_COMMIT,
                  window_id=receipt["window_id"], plan=plan(),
                  profile_identity_persisted=False, audio_persisted=False,
                  startup_warmups=receipt["external_warmup_calls"]))
        process = subprocess.Popen([str(python), "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=ROOT, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        job = None
        try:
            spec = importlib.util.spec_from_file_location("ad_three_owned_cpu_job",
                ROOT / "scripts/development/launcher/winjob.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            job = module.Job()
            job.assign(process)
            # 加入自有Job后才发管道许可；不会把外部模型服务加入该Job。
            process.stdin.write(json.dumps(payload).encode("utf-8"))
            process.stdin.close()
            supervise(process, time.monotonic() + min(seconds, validate_receipt(receipt, commit)), emit)
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            emit(dict(event="stopped", reason="bounded_run_incomplete_no_retry",
                      server_cleanup_unconfirmed=True, service_start_stop_performed=False))
            raise StopRun("bounded_run_incomplete_see_sanitized_summary") from None
        finally:
            try:
                if job is not None:
                    job.close()
                    emit(dict(event="owned_cpu_cleanup", process_tree_exit_confirmed=True,
                              external_model_service_stopped=False))
            finally:
                process.stdout.close()
                if not process.stdin.closed:
                    process.stdin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--url", default=URL)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_url(args.url)
    if args.worker:
        return worker(json.loads(sys.stdin.buffer.read()))
    if not args.run:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0
    if not all((args.receipt, args.production_root, args.output)):
        parser.error("--run requires --receipt, --production-root and --output")
    execute(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
