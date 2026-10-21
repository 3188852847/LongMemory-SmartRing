"""AI受控单实例窗口：默认只计划；不管理日用服务，不选择发布模式。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve()
HOST, PORT = "127.0.0.1", 18774
MAX_SECONDS, REQUEST_SECONDS = 300, 15
SOURCE_COMMIT = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
APPROVAL_SCOPE = "ai-current-voice-single-instance-window"
SERVICE_STAGES = {"service_import", "current_profile_read", "high_qos",
                  "model_load_and_reference_registration", "selected_voice_warmup", "http_bind", "serve"}


class WindowStopped(RuntimeError):
    pass


def plan():
    # 计划不读私人档案、不查端口/GPU，也不导入服务或torch。
    return dict(evidence_kind="plan_only_no_network_no_model", host=HOST, port=PORT,
                max_seconds=MAX_SECONDS, request_seconds=REQUEST_SECONDS,
                warmup_calls=2, driver_calls=14, max_total_synthesis_calls=16,
                profile_root="explicit_production_root_required",
                source_commit=SOURCE_COMMIT, fp16=True, hidden_only=True,
                model_streaming_default=False, force_buffered_audio=False,
                approval_scope=APPROVAL_SCOPE, approval_required=True,
                owns_only_new_service_and_cpu_client=True,
                daily_service_start_stop=False, automatic_mode_selection=False,
                seed_control="unavailable_in_existing_http_api",
                physical_playback_verified=False)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def left(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise WindowStopped("whole_window_deadline_exceeded")
    return value


def validate_approval(value, commit, production, *, now=None):
    now = now or datetime.now(timezone.utc)
    flags = ("production_stopped", "other_gpu_model_workers_stopped", "source_and_model_verified",
             "current_profile_root_verified", "single_model_instance")
    if (value.get("schema_version") != 1 or value.get("scope") != APPROVAL_SCOPE
            or value.get("reviewed_by") != "main_session"
            or value.get("candidate_commit") != commit
            or Path(value.get("checkout", "")).resolve() != ROOT
            or Path(value.get("production_root", "")).resolve() != production
            or value.get("url") != f"http://{HOST}:{PORT}/v1/audio/stream"
            or value.get("max_seconds") != MAX_SECONDS
            or value.get("physical_gpu_exclusive") is not False
            or not isinstance(value.get("window_id"), str) or not value["window_id"].strip()
            or not isinstance(value.get("shared_desktop_baseline"), dict)
            or any(value.get(flag) is not True for flag in flags)):
        raise WindowStopped("new_matching_main_session_approval_required")
    try:
        issued = datetime.fromisoformat(value["issued_at_utc"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(value["expires_at_utc"].replace("Z", "+00:00"))
        age = (now - issued).total_seconds()
        valid = (expires - now).total_seconds()
        if issued.tzinfo is None or expires.tzinfo is None or not 0 <= age <= 60 or valid < 1:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise WindowStopped("fresh_timezone_aware_approval_required") from None
    return min(MAX_SECONDS, valid)


def output_path(path):
    result = path.resolve()
    if (not result.is_relative_to(ROOT / "experiments/results")
            or result == ROOT / "experiments/results" or result.exists()):
        raise WindowStopped("new_owned_result_directory_required")
    return result


def git(args, cwd, deadline):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True,
        timeout=min(5, left(deadline)), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip()


def sanitized_environment():
    result = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONSTARTUP"}}
    result.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1", PYTHONDONTWRITEBYTECODE="1")
    return result


class SynthesisBudget:
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def consume(self):
        with self.lock:
            if self.calls >= 14:
                raise WindowStopped("fourteen_http_calls_plus_two_warmups_exhausted")
            self.calls += 1


def spawn_owned(command, job, *, payload=None, stdout=subprocess.DEVNULL):
    process = subprocess.Popen(command, cwd=ROOT, env=sanitized_environment(),
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=stdout, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        job.assign(process)
        if payload is not None:
            # 模型worker先阻塞读管道，只有归入自有Job后才获准加载模型。
            process.stdin.write((json.dumps(payload) + "\n").encode())
            process.stdin.flush()
        return process
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        raise


class ServiceEvents:
    """只收固定事件；不保存外部库日志/异常正文。"""
    def __init__(self, process):
        self.messages = queue.Queue()
        self.process = process
        self.reader = threading.Thread(target=self._read, daemon=True, name="ai-owned-service-events")
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(65537)
                if not line:
                    self.messages.put(None)
                    return
                if len(line) > 65536:
                    self.messages.put({"event": "invalid"})
                    return
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    value = {"event": "invalid"}
                self.messages.put(value)
        except (OSError, ValueError):
            self.messages.put(None)

    def get(self, timeout):
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            return "pending"


def await_service(events, deadline, emit, *, clock=time.monotonic):
    active, count, operation_deadline = None, 0, deadline
    while True:
        seconds = min(deadline, operation_deadline) - clock()
        if seconds <= 0:
            raise WindowStopped("service_startup_or_warmup_deadline_exceeded")
        value = events.get(min(.05, seconds))
        if value == "pending":
            continue
        if not isinstance(value, dict):
            raise WindowStopped("service_exited_before_ready")
        event = value.get("event")
        if event == "stage" and value.get("stage") in SERVICE_STAGES:
            emit(dict(event="stage", stage=value["stage"]))
        elif event == "warmup_begin":
            if active is not None or count >= 2 or value.get("index") != count:
                raise WindowStopped("warmup_order_or_call_budget_invalid")
            active, operation_deadline = count, min(deadline, clock() + REQUEST_SECONDS)
            emit(dict(event=event, index=count))
        elif event == "warmup_complete":
            seconds = value.get("seconds")
            if (active is None or value.get("index") != active
                    or type(seconds) not in (float, int) or not 0 <= seconds <= REQUEST_SECONDS):
                raise WindowStopped("warmup_completion_invalid")
            emit(dict(event=event, index=active, seconds=seconds))
            active, count, operation_deadline = None, count + 1, deadline
        elif event == "service_ready":
            identity = value.get("service_identity", {})
            if (active is not None or count != 2 or value.get("profile_root_explicit") is not True
                    or value.get("current_voice_identity_unchanged") is not True
                    or value.get("incremental_usable") is not True
                    or type(identity.get("pid")) is not int or identity["pid"] <= 0
                    or not identity.get("creation_token") or not identity.get("executable_path")):
                raise WindowStopped("service_ready_identity_or_warmup_invalid")
            emit(dict(event=event, warmup_calls=count, current_voice_identity_unchanged=True,
                      profile_root_explicit=True, incremental_usable=True))
            return identity
        elif event == "service_failed":
            emit(dict(event="service_failed", stage=value.get("stage") if value.get("stage") in SERVICE_STAGES else "worker_entry",
                      exception_class=str(value.get("exception_class", "unknown"))[:80],
                      reason_code="service_stage_failed"))
            raise WindowStopped("service_failed_no_retry")
        else:
            raise WindowStopped("service_failed_no_retry")


def supervise_client(process, events, deadline, *, clock=time.monotonic, pause=time.sleep):
    while process.poll() is None:
        if clock() >= deadline:
            raise WindowStopped("whole_window_deadline_exceeded")
        # 运行中服务异常或提前结束即停止，不用第二实例替补。
        value = events.get(0)
        if value != "pending":
            raise WindowStopped("service_stopped_during_matrix")
        pause(min(.05, max(0, deadline - clock())))
    if process.returncode:
        raise WindowStopped("driver_failed_no_retry_see_its_summary")


@contextmanager
def service_network():
    # 模型进程只接受18774客户端；不允许任何外部连接、DNS或bind其他端口。
    connect, connect_ex, resolve, bind = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.socket.bind
    def denied(*_args, **_kwargs):
        raise WindowStopped("model_network_connection_forbidden")
    def local_bind(sock, address):
        if address != (HOST, PORT):
            raise WindowStopped("model_bind_outside_fixed_port")
        return bind(sock, address)
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = denied, denied, denied
    socket.socket.bind = local_bind
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.socket.bind = connect, connect_ex, resolve, bind


def start_model_service(payload, emit):
    """只有受控worker获许可后调用；单测用fake模块，不在审查期实际加载。"""
    production, output = Path(payload["production_root"]), Path(payload["output"])
    sys.path.insert(0, str(HERE.parent))
    emit(dict(event="stage", stage="service_import"))
    import service
    from voice_profiles import VoiceProfileStore
    from windows_qos import apply_current_process_high_qos
    if Path(service.__file__).resolve() != HERE.with_name("service.py"):
        raise WindowStopped("candidate_service_source_mismatch")
    emit(dict(event="stage", stage="current_profile_read"))
    store = VoiceProfileStore(production)
    if not store.profile_path.is_file():
        raise WindowStopped("explicit_current_profile_required_no_default_fallback")
    expected = (store.profile()[1], store.model_context()[2])
    emit(dict(event="stage", stage="high_qos"))
    qos = apply_current_process_high_qos()
    def isolated_cache():
        cache = output / "runtime-cache"
        cache.mkdir(exist_ok=False)
        wetext = os.path.relpath(production / "local/runtime/modelscope-cache", ROOT)
        if not wetext.isascii():
            raise WindowStopped("existing_wetext_ascii_relative_path_required")
        os.environ.update(NUMBA_CACHE_DIR=str(cache / "numba"), MPLCONFIGDIR=str(cache / "matplotlib"),
                          HF_HOME=str(cache / "huggingface"), MODELSCOPE_CACHE=wetext)
        service._trial.install_modelscope_offline()
    service.configure_runtime_cache = isolated_cache
    budget = SynthesisBudget()
    driver = load_module("ai_window_service_driver_contract", HERE.with_name("benchmark_ad_three_modes.py"))
    class WindowSynthesizer(service.CosyVoiceSynthesizer):
        def _generate(self, text, context=None):
            # 既有构造器的默认参考暖机仍只执行一次；可见事件由父进程硬限15秒。
            if getattr(self, "_window_default_warmed", False):
                raise WindowStopped("extra_constructor_warmup_forbidden")
            self._window_default_warmed = True
            emit(dict(event="warmup_begin", index=0))
            began = time.monotonic()
            result = super()._generate(text, context)
            emit(dict(event="warmup_complete", index=0, seconds=time.monotonic() - began))
            return result

        def stream_chunks(self, text, **kwargs):
            if getattr(self, "_window_measurements_ready", False):
                if (text not in driver.TEXTS or kwargs.get("use_cache") is not False
                        or kwargs.get("voice_profile") is not None
                        or type(kwargs.get("model_streaming")) is not bool):
                    raise WindowStopped("only_reviewed_current_voice_uncached_v2_cases_allowed")
                budget.consume()
            yield from super().stream_chunks(text, **kwargs)
    source = production / "local/runtime/CosyVoice"
    emit(dict(event="stage", stage="model_load_and_reference_registration"))
    synth = WindowSynthesizer(source, source / "pretrained_models/Fun-CosyVoice3-0.5B",
        profile_root=production, hidden_only=True, model_streaming=False,
        force_buffered_audio=False, warm_selected_voice=False)
    synth.runtime_info["windows_qos"] = qos
    emit(dict(event="stage", stage="selected_voice_warmup"))
    emit(dict(event="warmup_begin", index=1))
    began = time.monotonic()
    synth.prepare_selected_voice()
    emit(dict(event="warmup_complete", index=1, seconds=time.monotonic() - began))
    actual = (store.profile()[1], store.model_context()[2])
    if expected != actual or synth.selected_warmup_identity != expected[1]:
        raise WindowStopped("current_profile_changed_during_startup")
    capability = service.backend_capabilities(synth)["audio_stream"]
    identity = capability.get("profile_identity", {})
    if ((identity.get("config_digest"), identity.get("context_digest")) != expected
            or identity.get("state") != "valid" or identity.get("selected_voice_warm") is not True):
        raise WindowStopped("service_profile_identity_not_matching_current_production_voice")
    if not capability["incremental_usable"]:
        raise WindowStopped("fixed_incremental_runtime_required")
    synth._window_measurements_ready = True
    emit(dict(event="stage", stage="http_bind"))
    server = service.CosyVoiceHTTPServer((HOST, PORT), synth)
    gpu = load_module("ai_window_worker_identity", HERE.with_name("gpu_window.py"))
    identity = gpu.image_identity(os.getpid())
    def control():
        # 仅父管道stop/EOF结束本实例；无公共关闭端点。
        sys.stdin.buffer.readline()
        server.shutdown()
    control_thread = threading.Thread(target=control, daemon=True, name="ai-owned-service-control")
    control_thread.start()
    emit(dict(event="service_ready", service_identity=identity, profile_root_explicit=True,
              current_voice_identity_unchanged=True, incremental_usable=True))
    try:
        # ready后不再向父事件管道写阶段，避免误判服务异常。
        server.serve_forever(poll_interval=.05)
    finally:
        server.server_close()


def service_worker():
    # stdin首行是父进程在Job归属完成后发出的唯一许可；之前不导入模型。
    payload = json.loads(sys.stdin.buffer.readline())
    stream = sys.stdout
    current_stage = ["worker_entry"]
    def emit(value):
        if value.get("event") == "stage":
            current_stage[0] = value["stage"]
        stream.write(json.dumps(value) + "\n")
        stream.flush()
    try:
        with open(os.devnull, "w") as discard, redirect_stdout(discard), redirect_stderr(discard), service_network():
            start_model_service(payload, emit)
        return 0
    except BaseException as error:
        emit(dict(event="service_failed", stage=current_stage[0],
                  exception_class=type(error).__name__[:80], reason_code="service_stage_failed",
                  error_details_persisted=False))
        return 1


def execute(args):
    # 全窗口从执行入口开始计时，不能在加载后重置300秒。
    started_at, began = datetime.now(timezone.utc), time.monotonic()
    deadline = began + MAX_SECONDS
    production = args.production_root.resolve()
    commit = git(["rev-parse", "HEAD"], ROOT, deadline)
    if git(["status", "--porcelain"], ROOT, deadline):
        raise WindowStopped("clean_committed_candidate_required")
    approval = json.loads(args.approval.read_text("utf-8-sig"))
    deadline = min(deadline, began + validate_approval(approval, commit, production, now=started_at))
    output = output_path(args.output)
    source = production / "local/runtime/CosyVoice"
    cosy_python = source / ".venv/Scripts/python.exe"
    client_python = production / ".venv/Scripts/python.exe"
    if (production == ROOT or not cosy_python.is_file() or not client_python.is_file()
            or not (production / "local/config/voices/CosyVoice3.json").is_file()):
        raise WindowStopped("separate_production_root_with_installed_runtimes_and_profile_required")
    if (git(["rev-parse", "HEAD"], source, deadline) != SOURCE_COMMIT
            or git(["status", "--porcelain", "--untracked-files=no"], source, deadline)):
        raise WindowStopped("fixed_clean_external_source_required")
    # 只尝试绑定固定实验端口，随即释放；占用时绝不查找/停止其所有者。
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind((HOST, PORT))
    output.mkdir(parents=True, exist_ok=False)
    job = service = client = events = None
    with (output / "window-summary.jsonl").open("x", encoding="utf-8") as file:
        def emit(value):
            file.write(json.dumps(value, ensure_ascii=False) + "\n")
            file.flush()
        emit(dict(event="window_start", candidate_commit=commit, source_commit=SOURCE_COMMIT,
                  window_id=approval["window_id"], started_at_utc=started_at.isoformat(), plan=plan(),
                  private_profile_and_audio_persisted=False))
        confirmed = False
        stage = "preflight_gpu"
        try:
            gpu = load_module("ai_window_preflight_gpu", HERE.with_name("gpu_window.py"))
            report = gpu.ensure_window(approval)
            emit(dict(event="preflight_gpu_pass", approved_background_count=len(report["approved"]),
                      physical_gpu_exclusive=False))
            left(deadline)
            owner = load_module("ai_window_process_owner", ROOT / "scripts/development/launcher/winjob.py")
            job = owner.Job()
            payload = dict(production_root=str(production), output=str(output))
            stage = "spawn_owned_service"
            service = spawn_owned([str(cosy_python), "-B", "-X", "utf8", str(HERE), "--service-worker"],
                job, payload=payload, stdout=subprocess.PIPE)
            events = ServiceEvents(service)
            stage = "await_service_and_warmups"
            identity = await_service(events, deadline, emit)
            receipt = {**approval, "scope": "ad-three-mode-external-single-instance",
                "started_at_utc": started_at.isoformat(),
                "expires_at_utc": (started_at + timedelta(seconds=deadline - began)).isoformat(),
                "external_warmup_calls": 2, "service_identity": identity,
                "external_service_startup_warmups_within_15s_each": True,
                "service_source_matches_candidate": True}
            receipt_path = output / "driver-resource-receipt.json"
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
            left(deadline)
            driver = HERE.with_name("benchmark_ad_three_modes.py")
            client_args = [str(driver), "--run", "--receipt", str(receipt_path),
                           "--production-root", str(production), "--output", str(output / "driver")]
            stage = "spawn_owned_client"
            client = spawn_owned([str(client_python), "-B", "-X", "utf8", str(HERE), "--client-worker"],
                job, payload=dict(argv=client_args))
            stage = "three_mode_matrix"
            supervise_client(client, events, deadline)
            # 退出0仍须有驱动最后的完整/清理事件；不只信进程返回码。
            stage = "verify_driver_completion"
            summary = [json.loads(line) for line in (output / "driver/summary.jsonl").read_text("utf-8").splitlines()]
            if (sum(x.get("event") == "complete" for x in summary) != 1
                    or not any(x.get("event") == "owned_cpu_cleanup" and x.get("process_tree_exit_confirmed") is True for x in summary)):
                raise WindowStopped("driver_complete_and_owned_cpu_cleanup_required")
            left(deadline)
            confirmed = True
            emit(dict(event="driver_complete", automatic_mode_selection=False, physical_playback_verified=False))
        except BaseException as error:
            emit(dict(event="window_failed", stage=stage, exception_class=type(error).__name__[:80],
                      reason_code=str(error) if type(error) is WindowStopped else "window_stage_failed",
                      details_persisted=False, retry_performed=False))
            raise WindowStopped("window_incomplete_see_owned_sanitized_results") from None
        finally:
            # 先请求正常退出；任何失败/超时都以自有Job完整退出核验收尾。
            if service is not None and service.poll() is None:
                try:
                    service.stdin.write(b"stop\n")
                    service.stdin.flush()
                    service.wait(timeout=min(1, max(.001, deadline - time.monotonic())))
                except (OSError, subprocess.TimeoutExpired):
                    pass
            tree_confirmed = False
            try:
                if job is not None:
                    job.close()
                    tree_confirmed = True
            finally:
                for process in (client, service):
                    if process is not None:
                        process.wait(timeout=1)
                        if process.stdin is not None:
                            process.stdin.close()
                        if process.stdout is not None:
                            process.stdout.close()
                if events is not None:
                    events.reader.join(timeout=.2)
                emit(dict(event="window_cleanup", driver_complete=confirmed,
                    owned_process_tree_exit_confirmed=tree_confirmed,
                    event_reader_stopped=events is None or not events.reader.is_alive(),
                    daily_service_start_stop=False, total_wall_seconds=time.monotonic() - began,
                    forced_exit_does_not_prove_kernel_preemption=True,
                    root_must_verify_resources_before_daily_restore=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--service-worker", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--client-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.service_worker:
        return service_worker()
    if args.client_worker:
        payload = json.loads(sys.stdin.buffer.readline())
        sys.argv = payload["argv"]
        driver = load_module("ai_owned_ad_client_entry", HERE.with_name("benchmark_ad_three_modes.py"))
        return driver.main()
    if not args.run:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return 0
    if not all((args.approval, args.production_root, args.output)):
        parser.error("--run requires --approval, --production-root and --output")
    if os.name != "nt":
        raise WindowStopped("windows_owned_job_required")
    execute(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
