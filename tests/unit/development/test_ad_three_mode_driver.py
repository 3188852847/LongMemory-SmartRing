"""AD三模式驱动的合成传输/预算契约；无GPU、私人档案或日用HTTP请求。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
from types import SimpleNamespace
import wave

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/development/cosyvoice/benchmark_ad_three_modes.py"
spec = importlib.util.spec_from_file_location("ad_three_mode_driver_test", PATH)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
sys.path.insert(0, str(ROOT / "scripts/development/xiaozhi"))
import cosyvoice_streaming as consumer


def receipt(now):
    return dict(schema_version=1, scope="ad-three-mode-external-single-instance",
        reviewed_by="main_session", candidate_commit="abc", checkout=str(ROOT), url=driver.URL,
        window_id="synthetic-test", production_stopped=True, other_gpu_model_workers_stopped=True,
        single_model_instance=True, service_source_matches_candidate=True, source_and_model_verified=True,
        external_service_startup_warmups_within_15s_each=True, external_warmup_calls=2,
        max_seconds=300, physical_gpu_exclusive=False, shared_desktop_baseline={},
        service_identity=dict(pid=123, creation_token="fake", executable_path="fake-python.exe"),
        started_at_utc=(now - timedelta(seconds=20)).isoformat(),
        expires_at_utc=(now + timedelta(seconds=500)).isoformat())


def good_health():
    return dict(ready=True, requires_restart=False, generation_in_flight=False,
        warmup_seconds=1.0, selected_voice_warmup_seconds=1.5,
        selected_voice_warm=True, stream_runtime=dict(applied=True, active_requests=0),
        runtime=dict(fp16=True, hidden_only=True,
                     service_sha256=hashlib.sha256((ROOT / "scripts/development/cosyvoice/service.py").read_bytes()).hexdigest()),
        diagnostics={name: dict(calls=0, wall_ms=0) for name in ("llm_job", "flow", "hift", "text_normalize")},
        capabilities=dict(audio_stream=dict(incremental_usable=True, force_buffered=False,
            profile_identity=dict(state="valid", selected_voice_warm=True,
                                  context_digest="synthetic-context", config_digest="synthetic-config"))))


def wav(samples, amplitude=5000):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(24000)
        file.writeframes(struct.pack("<h", amplitude) * samples)
    return output.getvalue()


class FakeEncoder:
    def __init__(self):
        self.pending = b""
        self.resets = 0
        self.events = []

    def reset_state(self):
        self.pending = b""
        self.resets += 1

    def encode_pcm_to_opus_stream(self, data, *, end_of_stream, callback):
        self.pending += data
        while len(self.pending) >= 2880:
            packet, self.pending = self.pending[:2880], self.pending[2880:]
            callback(packet)
        if end_of_stream and self.pending:
            packet = self.pending.ljust(2880, b"\0")
            self.pending = b""
            callback(packet)


class FakeDecoder:
    def decode(self, packet, _frame_size):
        return packet


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(calls=[], responses=[], chunks=[wav(720), wav(1800), wav(841)],
                            status=200, eos=True, trailing=b"", closed=0, shutdown=0, partial=True,
                            headers={"Content-Type": "application/vnd.longmemory.wav-chunks",
                                     "X-LongMemory-Audio-Stream": "2"})
    class Response(io.BytesIO):
        def __init__(self):
            body = b"".join(struct.pack("!I", len(chunk)) + chunk for chunk in state.chunks)
            body += (b"\0" * 4 if state.eos else b"") + state.trailing
            super().__init__(body)
            self.status, self.headers = state.status, dict(state.headers)
            self.eof_read = False
            state.responses.append(self)

        def read(self, size=-1):
            value = super().read(min(size, 11) if state.partial and size > 0 else size)
            if not value:
                self.eof_read = True
            return value

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == (driver.HOST, driver.PORT)
            assert 0 < timeout <= 2
            self.sock = SimpleNamespace(settimeout=lambda _: None, shutdown=self.shutdown)

        def shutdown(self, _how):
            state.shutdown += 1

        def connect(self):
            pass

        def request(self, method, path, body, headers):
            assert method == "POST" and path == "/v1/audio/stream"
            state.calls.append(json.loads(body))

        def getresponse(self):
            return Response()

        def close(self):
            state.closed += 1

    monkeypatch.setattr(driver.http.client, "HTTPConnection", Connection)
    return state


def case(mode="incremental", kind="measurement"):
    return dict(mode=mode, kind=kind, text_id=0, repeat=0)


def run(case_value, encoder=None):
    return driver.run_case(case_value, consumer, encoder or FakeEncoder(), FakeDecoder(),
                           driver.time.monotonic() + 2)


def test_default_plan_is_exact_bounded_matrix_and_imports_no_torch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(PATH)])
    monkeypatch.setattr(driver.socket.socket, "connect", lambda *_: pytest.fail("plan connected"))
    assert driver.main() == 0
    value = json.loads(capsys.readouterr().out)
    assert value["url"] == driver.URL
    assert value["measured_calls"] + value["cancel_calls"] + value["reuse_calls"] + 2 == 16
    assert value["max_seconds"] == 300 and value["request_seconds"] == 15
    rows = value["rows"]
    assert len(rows) == 14
    assert [r["mode"] for r in rows[:3]] == list(driver.MODES)
    assert [r["mode"] for r in rows[6:9]] == list(reversed(driver.MODES))
    assert all(sum(r["text_id"] == text_id and r["mode"] == mode for r in rows[:12]) == 2
               for text_id in range(2) for mode in driver.MODES)
    assert "seed" not in rows[0] and value["seed_control"].startswith("unavailable")


@pytest.mark.parametrize("url", ["http://127.0.0.1:18770/v1/audio/stream",
    "http://localhost:18774/v1/audio/stream", "http://127.0.0.1:18774/v1/audio/stream?x=1",
    "http://127.0.0.1:8003/v1/audio/stream", "https://127.0.0.1:18774/v1/audio/stream"])
def test_fixed_port_rejects_daily_aliases_and_url_variants(url):
    with pytest.raises(ValueError, match="fixed_isolated"):
        driver.validate_url(url)


def test_socket_fence_rejects_every_other_target_and_restores():
    original = socket.socket.connect
    with driver.fixed_network():
        with socket.socket() as sock, pytest.raises(driver.StopRun, match="outside_fixed_port"):
            sock.connect(("127.0.0.1", 18770))
        with pytest.raises(driver.StopRun, match="dns_outside"):
            socket.getaddrinfo("example.invalid", 443)
    assert socket.socket.connect is original


@pytest.mark.parametrize("change", [dict(production_stopped=False), dict(single_model_instance=False),
    dict(candidate_commit="other"), dict(external_warmup_calls=3), dict(url="http://127.0.0.1:18770"),
    dict(external_service_startup_warmups_within_15s_each=False), dict(service_identity={})])
def test_receipt_refuses_scope_warmup_identity_or_commit_mismatch(change):
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        driver.validate_receipt({**receipt(now), **change}, "abc", now=now)


def test_startup_and_expiry_consume_same_300_second_budget():
    now = datetime.now(timezone.utc)
    value = receipt(now)
    assert driver.validate_receipt(value, "abc", now=now) == 280
    value["expires_at_utc"] = (now + timedelta(seconds=30)).isoformat()
    assert driver.validate_receipt(value, "abc", now=now) == 30
    value["started_at_utc"] = (now - timedelta(seconds=301)).isoformat()
    with pytest.raises(ValueError, match="expired"):
        driver.validate_receipt(value, "abc", now=now)


@pytest.mark.parametrize("mode", driver.MODES)
def test_partial_wire_normal_eos_exact_samples_and_padding(mode, wire):
    row = run(case(mode))
    assert row["outcome"] == "complete" and row["eos"]
    assert row["pcm_samples"] == 3361 and row["wav_chunks"] == 3
    assert row["opus_frames"] == 3 and row["decoded_samples"] == 4320
    assert row["tail_padding_samples"] == 959
    assert 0 <= row["first_pcm_ms"] <= row["first_opus_ms"] <= row["first_energy_opus_ms"]
    assert row["estimated_supply"]["playable_ms"] == 180
    assert row["owned_socket_watcher_stopped"]
    assert len(wire.calls) == 1 and wire.closed == 1
    assert wire.calls[0] == dict(input=driver.TEXTS[0], response_format="wav", stream=True,
        cache=False, delivery_mode="buffered" if mode == "buffered" else "incremental")
    if mode == "adaptive":
        assert row["adaptive_buffer"]["reader_stopped"]


@pytest.mark.parametrize("mode,first_after_eof", [("buffered", True), ("incremental", False)])
def test_buffered_delivery_barrier_and_incremental_early_release(mode, first_after_eof, wire):
    encoder = FakeEncoder()
    statuses = []
    original = encoder.encode_pcm_to_opus_stream
    def observe(data, *, end_of_stream, callback):
        def delivered(packet):
            statuses.append(wire.responses[0].eof_read)
            callback(packet)
        return original(data, end_of_stream=end_of_stream, callback=delivered)
    encoder.encode_pcm_to_opus_stream = observe
    run(case(mode), encoder)
    assert statuses[0] is first_after_eof


@pytest.mark.parametrize("mutation", ["missing_eos", "truncated_wav", "trailing", "wrong_header", "busy", "silent"])
def test_bad_wire_fails_without_retry_or_fallback(mutation, wire):
    if mutation == "missing_eos":
        wire.eos = False
    elif mutation == "truncated_wav":
        wire.chunks[-1] = wire.chunks[-1][:-2]
    elif mutation == "trailing":
        wire.trailing = b"x"
    elif mutation == "wrong_header":
        wire.headers["X-LongMemory-Audio-Stream"] = "1"
    elif mutation == "busy":
        wire.status = 503
    else:
        wire.chunks = [wav(1440, 0)]
    with pytest.raises((driver.StopRun, ValueError, EOFError)):
        run(case())
    assert len(wire.calls) == 1 and wire.closed == 1


def test_energy_requires_contiguous_5ms_across_frames():
    gate = driver.EnergyGate()
    assert not gate.feed(struct.pack("<h", 32767) + b"\0\0" * 119)
    gate = driver.EnergyGate()
    assert not gate.feed(struct.pack("<h", -200) * 60)
    assert gate.feed(struct.pack("<h", 200) * 60)


def test_rms_gate_accepts_normal_zero_crossing_sine_across_frames():
    # 400Hz峰值300的RMS约212，旧逐样本门每次过零都清空，必然误拒。
    pcm = struct.pack("<120h", *(round(300 * math.sin(2 * math.pi * 400 * i / driver.RATE)) for i in range(120)))
    gate = driver.EnergyGate()
    assert not gate.feed(pcm[:82])
    assert not gate.feed(pcm[82:210])
    assert gate.feed(pcm[210:])


@pytest.mark.parametrize("kind", ["silence", "isolated_full_scale_spike", "quiet_sine"])
def test_rms_gate_rejects_silence_or_isolated_peak_or_below_threshold(kind):
    samples = [0] * 1440
    if kind == "isolated_full_scale_spike":
        samples[711] = -32768
    elif kind == "quiet_sine":
        samples = [round(100 * math.sin(2 * math.pi * 400 * i / driver.RATE)) for i in range(1440)]
    gate = driver.EnergyGate()
    pcm = struct.pack("<1440h", *samples)
    assert not gate.feed(pcm[:1424])
    assert not gate.feed(pcm[1424:])


def test_energy_cancel_joins_own_reader_resets_same_encoder_and_reuses(monkeypatch, wire):
    live = good_health()
    live.update(generation_in_flight=True, stream_runtime=dict(applied=True, active_requests=1))
    monkeypatch.setattr(driver, "health", lambda _: live)
    encoder = FakeEncoder()
    cancelled = run(case("adaptive", "cancel_after_energy"), encoder)
    assert cancelled["outcome"] == "intentional_cancel"
    assert cancelled["cancel_live_work_observed"] and cancelled["cancel_triggered"]
    assert cancelled["packets_after_cancel"] == 0
    assert cancelled["adaptive_buffer"]["reader_stopped"]
    assert not encoder.pending
    resumed = run(case("adaptive", "reuse"), encoder)
    assert resumed["outcome"] == "complete" and resumed["pcm_samples"] == 3361
    assert encoder.resets == 4 and len(wire.calls) == 2


def test_finished_generation_is_not_claimed_as_real_cancel(monkeypatch, wire):
    monkeypatch.setattr(driver, "health", lambda _: good_health())
    with pytest.raises(driver.StopRun, match="no_cancel_proof"):
        run(case("adaptive", "cancel_after_energy"))
    assert len(wire.calls) == 1


def test_profile_drift_force_buffering_and_restart_fail_closed():
    health = good_health()
    identity = driver.check_health(health)
    health["capabilities"]["audio_stream"]["profile_identity"]["context_digest"] = "changed"
    with pytest.raises(driver.StopRun, match="profile_changed"):
        driver.check_health(health, identity)
    for key in ("force_buffered", "incremental_usable"):
        health = good_health()
        health["capabilities"]["audio_stream"][key] = key == "force_buffered"
        with pytest.raises(driver.StopRun):
            driver.check_health(health)
    health = good_health()
    health["requires_restart"] = True
    with pytest.raises(driver.StopRun):
        driver.check_health(health)
    health = good_health()
    health["selected_voice_warmup_seconds"] = 15.01
    with pytest.raises(driver.StopRun):
        driver.check_health(health)


def test_coarse_diagnostic_deltas_are_not_gpu_sum():
    assert driver.diagnostic_delta({"flow": dict(calls=2, wall_ms=10)},
        {"flow": dict(calls=3, wall_ms=25)})["flow"] == dict(calls=1, wall_ms=15)
    with pytest.raises(driver.StopRun, match="reset"):
        driver.diagnostic_delta({"flow": dict(calls=2, wall_ms=10)},
                                {"flow": dict(calls=0, wall_ms=0)})


def test_matrix_budget_and_cancel_cleanup_precede_reuse(monkeypatch):
    events, seen = [], []
    value = good_health()
    monkeypatch.setattr(driver, "health", lambda _: value)
    monkeypatch.setattr(driver, "idle_health", lambda *_: (value, 2.0))
    def fake_case(row, *_):
        seen.append(row["kind"])
        return dict(row, outcome="intentional_cancel" if row["kind"] == "cancel_after_energy" else "complete")
    monkeypatch.setattr(driver, "run_case", fake_case)
    result = driver.matrix(None, None, lambda: None, driver.time.monotonic() + 10, 2,
                           events.append, lambda: None)
    assert result["calls_including_external_warmups"] == 16
    assert seen[-2:] == ["cancel_after_energy", "reuse"]
    assert len([event for event in events if event["event"] == "operation_complete"]) == 14
    assert all(event["row"]["server_idle_after"] for event in events if event["event"] == "operation_complete")
    assert "synthetic-context" not in json.dumps(events)


def test_failure_stops_matrix_without_replacement_or_reuse(monkeypatch):
    calls = []
    monkeypatch.setattr(driver, "health", lambda _: good_health())
    def fail(row, *_):
        calls.append(row)
        raise driver.StopRun("synthetic_failure")
    monkeypatch.setattr(driver, "run_case", fail)
    with pytest.raises(driver.StopRun):
        driver.matrix(None, None, lambda: None, driver.time.monotonic() + 10, 2,
                      lambda _: None, lambda: None)
    assert len(calls) == 1


class FakeProcess:
    def __init__(self, messages, returncode=None):
        self.stdout = io.BytesIO(b"".join(json.dumps(item).encode() + b"\n" for item in messages))
        self.returncode = returncode
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -1

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


@pytest.mark.parametrize("wall_deadline", [0, 300])
def test_parent_hard_wall_and_each_operation_deadline_kill_only_owned_cpu_process(wall_deadline):
    child = FakeProcess([dict(event="operation_begin", index=0, kind="measurement")])
    now = [0]
    def clock():
        value = now[0]
        now[0] += 16
        return value
    with pytest.raises((driver.StopRun, subprocess.TimeoutExpired)):
        driver.supervise(child, wall_deadline, lambda _: None, clock=clock)
    assert child.killed


@pytest.mark.parametrize("messages", [
    [dict(event="complete", rows_completed=14, calls_including_external_warmups=16)],
    [dict(event="operation_begin", index=0, kind="measurement")] * 2,
    [dict(event="operation_complete", row=dict(index=0, server_idle_after=True))],
])
def test_parent_rejects_missing_rows_or_repeated_begin_that_would_reset_budget(messages):
    child = FakeProcess(messages)
    with pytest.raises(driver.StopRun):
        driver.supervise(child, 300, lambda _: None, clock=lambda: 0)
    assert child.killed


def test_parent_accepts_only_complete_ordered_idle_matrix():
    messages = []
    for index, row in enumerate(driver.plan()["rows"]):
        messages.extend([dict(event="operation_begin", index=index, kind=row["kind"]),
                         dict(event="operation_complete", row=dict(index=index, server_idle_after=True))])
    messages.append(dict(event="complete", rows_completed=14, calls_including_external_warmups=16))
    child = FakeProcess(messages, returncode=0)
    events = []
    driver.supervise(child, 300, events.append, clock=lambda: 0)
    assert not child.killed and len(events) == 29


def test_worker_failure_is_sanitized_and_does_not_load_model(monkeypatch, capsys):
    monkeypatch.setattr(driver, "validate_receipt", lambda *_: 1)
    def fail(_):
        raise RuntimeError("PRIVATE-REFERENCE-PATH-AND-TEXT")
    monkeypatch.setattr(driver, "gpu_guard", fail)
    assert driver.worker(dict(receipt={}, commit="abc", voice_root="unused")) == 1
    value = capsys.readouterr().out
    assert "PRIVATE" not in value and json.loads(value)["server_cleanup_unconfirmed"]


@pytest.mark.parametrize("pid,owned_model,allowed", [(123, True, True), (456, True, False), (123, False, False)])
def test_resource_guard_requires_fixed_listener_owner_and_matching_model_identity(monkeypatch, pid, owned_model, allowed):
    observed = []
    def ensure(value, *, own_identity):
        observed.append(own_identity)
        return dict(approved=[dict(classification="owned_benchmark_model")] if owned_model else [])
    def exec_module(module):
        module.ensure_window = ensure
    monkeypatch.setattr(driver.importlib.util, "spec_from_file_location",
                        lambda *_: SimpleNamespace(loader=SimpleNamespace(exec_module=exec_module)))
    monkeypatch.setattr(driver.importlib.util, "module_from_spec", lambda _: SimpleNamespace())
    def snapshot(command, **kwargs):
        assert "18774" in command[-1] and kwargs["timeout"] == 5
        return json.dumps(pid).encode()
    monkeypatch.setattr(driver.subprocess, "check_output", snapshot)
    value = receipt(datetime.now(timezone.utc))
    if allowed:
        driver.gpu_guard(value)
        assert observed == [value["service_identity"]]
    else:
        with pytest.raises(driver.StopRun):
            driver.gpu_guard(value)


MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
VOICE = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
VOICE_PYTHON = VOICE / ".venv/Scripts/python.exe"


@pytest.mark.skipif(not VOICE_PYTHON.is_file(), reason="owner-installed CPU Opus environment unavailable")
@pytest.mark.parametrize("waveform", ["dc", "400hz_zero_crossing"])
def test_real_http_framing_and_installed_cpu_opus_all_three_modes(waveform):
    """测试专用factory把固定目标转至自有随机端口；不打开18774或任何日用端口。"""
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.path == "/v1/audio/stream"
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.longmemory.wav-chunks")
            self.send_header("X-LongMemory-Audio-Stream", "2")
            self.end_headers()
            for samples in (720, 1800, 841):
                if waveform == "dc":
                    value = wav(samples)
                else:
                    audio = io.BytesIO()
                    with wave.open(audio, 'wb') as file:
                        file.setnchannels(1); file.setsampwidth(2); file.setframerate(24000)
                        file.writeframes(struct.pack(f'<{samples}h', *(
                            round(5000 * math.sin(2 * math.pi * 400 * i / 24000)) for i in range(samples))))
                    value = audio.getvalue()
                self.wfile.write(struct.pack("!I", len(value)) + value)
                self.wfile.flush()
            self.wfile.write(b"\0" * 4)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    script = r'''
import importlib.util,json,sys,time
from pathlib import Path
p=json.loads(sys.stdin.buffer.read())
s=importlib.util.spec_from_file_location("ad_three_cpu_probe",p["driver"])
d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
c,e,decoder,dll=d.load_cpu(Path(p["voice"]))
original=d.http.client.HTTPConnection
def local_connection(host,port,timeout):
    assert (host,port)==(d.HOST,d.PORT)
    return original("127.0.0.1",p["port"],timeout=timeout)
d.http.client.HTTPConnection=local_connection
try:
    rows=[d.run_case(dict(mode=mode,kind="measurement",text_id=0),c,e,decoder(),time.monotonic()+3) for mode in d.MODES]
    print(json.dumps(dict(rows=rows,torch_imported="torch" in sys.modules)))
finally:
    e.close();dll.close()
'''
    try:
        environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONSTARTUP"}}
        result = subprocess.run([str(VOICE_PYTHON), "-B", "-X", "utf8", "-c", script],
            input=json.dumps(dict(driver=str(PATH), voice=str(VOICE), port=server.server_port)).encode(),
            capture_output=True, timeout=15, cwd=ROOT, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-1200:]
        report = json.loads(result.stdout)
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
    assert report["torch_imported"] is False
    assert len(calls) == 3
    assert [item["delivery_mode"] for item in calls] == ["buffered", "incremental", "incremental"]
    assert all(item["cache"] is False and "seed" not in item for item in calls)
    for row in report["rows"]:
        assert row["outcome"] == "complete" and row["eos"]
        assert row["pcm_samples"] == 3361 and row["decoded_samples"] == 4320
        assert row["first_energy_opus_ms"] is not None and row["opus_frames"] == 3
