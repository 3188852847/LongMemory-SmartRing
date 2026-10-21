"""AI窗口的资源/所有权契约；fake模型及自有CPU进程，不启动GPU服务。"""

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / 'scripts/development/cosyvoice/run_ad_three_mode_window.py'
spec = importlib.util.spec_from_file_location('ai_three_window_test', PATH)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def approval(now, production):
    return dict(schema_version=1, scope=w.APPROVAL_SCOPE, reviewed_by='main_session',
        candidate_commit='synthetic', checkout=str(ROOT), production_root=str(production),
        url=f'http://{w.HOST}:{w.PORT}/v1/audio/stream', max_seconds=300,
        physical_gpu_exclusive=False, window_id='new-synthetic', shared_desktop_baseline={},
        production_stopped=True, other_gpu_model_workers_stopped=True,
        source_and_model_verified=True, current_profile_root_verified=True,
        single_model_instance=True, issued_at_utc=(now-timedelta(seconds=1)).isoformat(),
        expires_at_utc=(now+timedelta(seconds=299)).isoformat())


def test_plan_no_network_process_model_or_private_io(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', [str(PATH)])
    monkeypatch.setattr(w.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('plan spawned'))
    monkeypatch.setattr(w.socket, 'socket', lambda *_a, **_k: pytest.fail('plan socket'))
    monkeypatch.setattr(w, 'load_module', lambda *_: pytest.fail('plan imported service'))
    assert w.main() == 0
    value = json.loads(capsys.readouterr().out)
    assert value['warmup_calls'] + value['driver_calls'] == 16
    assert value['max_seconds'] == 300 and value['request_seconds'] == 15
    assert value['profile_root'] == 'explicit_production_root_required'
    assert not value['daily_service_start_stop']


@pytest.mark.parametrize('change', [dict(candidate_commit='stale'), dict(production_stopped=False),
    dict(source_and_model_verified=False), dict(current_profile_root_verified=False),
    dict(url='http://127.0.0.1:18770/v1/audio/stream'), dict(physical_gpu_exclusive=True),
    dict(max_seconds=600), dict(scope='ad-three-mode-external-single-instance')])
def test_approval_rejects_stale_scope_or_unverified_window(change, tmp_path):
    now = datetime.now(timezone.utc)
    with pytest.raises(w.WindowStopped):
        w.validate_approval({**approval(now, tmp_path), **change}, 'synthetic', tmp_path, now=now)


def test_approval_expiry_is_not_extended_and_old_window_cannot_be_reused(tmp_path):
    now = datetime.now(timezone.utc)
    value = approval(now, tmp_path)
    assert w.validate_approval(value, 'synthetic', tmp_path, now=now) == 299
    value['issued_at_utc'] = (now-timedelta(seconds=61)).isoformat()
    with pytest.raises(w.WindowStopped, match='fresh'):
        w.validate_approval(value, 'synthetic', tmp_path, now=now)


class Events:
    def __init__(self, rows):
        self.rows = iter(rows)

    def get(self, _timeout):
        return next(self.rows, 'pending')


def warmups():
    return [dict(event='warmup_begin', index=0), dict(event='warmup_complete', index=0, seconds=1),
            dict(event='warmup_begin', index=1), dict(event='warmup_complete', index=1, seconds=2)]


def ready():
    return dict(event='service_ready', profile_root_explicit=True, current_voice_identity_unchanged=True,
        incremental_usable=True, service_identity=dict(pid=123, creation_token='test', executable_path='test'))


def test_exact_two_warmups_and_explicit_current_voice_are_required():
    seen = []
    assert w.await_service(Events(warmups()+[ready()]), 300, seen.append, clock=lambda: 0)['pid'] == 123
    assert len(seen) == 5 and 'service_identity' not in seen[-1]
    with pytest.raises(w.WindowStopped):
        w.await_service(Events([ready()]), 300, lambda _: None, clock=lambda: 0)


@pytest.mark.parametrize('rows', [
    [dict(event='warmup_begin', index=0)]*2,
    [dict(event='warmup_begin', index=0), dict(event='warmup_complete', index=0, seconds=15.001)],
    warmups()+[dict(event='warmup_begin', index=2)],
    warmups()+[{**ready(), 'profile_root_explicit': False}],
    [dict(event='service_failed')],
])
def test_warmup_failure_or_extra_call_stops_without_retry(rows):
    with pytest.raises(w.WindowStopped):
        w.await_service(Events(rows), 300, lambda _: None, clock=lambda: 0)


@pytest.mark.parametrize('whole_deadline', [300, 5])
def test_independent_whole_window_and_warmup_15_second_deadlines(whole_deadline):
    now = iter([0, 0, 16])
    with pytest.raises(w.WindowStopped, match='deadline'):
        w.await_service(Events([dict(event='warmup_begin', index=0)]), whole_deadline,
                        lambda _: None, clock=lambda: next(now))


def test_service_death_or_driver_timeout_never_starts_replacement():
    p = SimpleNamespace(poll=lambda: None)
    with pytest.raises(w.WindowStopped, match='service_stopped'):
        w.supervise_client(p, Events([None]), 300, clock=lambda: 0, pause=lambda _: None)
    with pytest.raises(w.WindowStopped, match='deadline'):
        w.supervise_client(p, Events([]), 300, clock=lambda: 301, pause=lambda _: None)


def test_service_failure_keeps_stage_and_class_without_private_exception_text(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'{}\n')))
    def fail(_payload, emit):
        emit(dict(event='stage', stage='current_profile_read'))
        raise ValueError('PRIVATE-VOICE-PATH-CONTENT')
    monkeypatch.setattr(w, 'start_model_service', fail)
    assert w.service_worker() == 1
    text = capsys.readouterr().out
    assert 'PRIVATE' not in text
    failure = json.loads(text.splitlines()[-1])
    assert failure['stage'] == 'current_profile_read' and failure['exception_class'] == 'ValueError'
    assert failure['reason_code'] == 'service_stage_failed'


def test_service_http_budget_is_fourteen_plus_exact_two_warmups():
    budget = w.SynthesisBudget()
    for _ in range(14):
        budget.consume()
    with pytest.raises(w.WindowStopped, match='exhausted'):
        budget.consume()
    assert budget.calls == 14


def test_spawn_assigns_job_before_permission_and_failure_sends_nothing(monkeypatch):
    sequence = []
    class Pipe(io.BytesIO):
        def write(self, data):
            sequence.append('permission')
            return super().write(data)
    process = SimpleNamespace(stdin=Pipe(), stdout=None, poll=lambda: None,
        kill=lambda: sequence.append('kill'), wait=lambda **_: None)
    monkeypatch.setattr(w.subprocess, 'Popen', lambda *_a, **_k: process)
    job = SimpleNamespace(assign=lambda _: sequence.append('assign'))
    w.spawn_owned(['test'], job, payload={'safe': True})
    assert sequence == ['assign', 'permission']
    sequence.clear()
    def fail(_):
        raise OSError('synthetic')
    with pytest.raises(OSError):
        w.spawn_owned(['test'], SimpleNamespace(assign=fail), payload={})
    assert sequence == ['kill']


def test_model_network_fence_blocks_connections_and_other_binds_without_touching_ports(monkeypatch):
    seen = []
    monkeypatch.setattr(socket.socket, 'bind', lambda _s, addr: seen.append(addr))
    with w.service_network(), socket.socket() as sock:
        for method in (sock.connect, sock.connect_ex):
            with pytest.raises(w.WindowStopped):
                method(('127.0.0.1', 18770))
        with pytest.raises(w.WindowStopped):
            socket.getaddrinfo('example.invalid', 443)
        with pytest.raises(w.WindowStopped):
            sock.bind(('127.0.0.1', 8003))
        sock.bind(('127.0.0.1', 18774))
    assert seen == [('127.0.0.1', 18774)]


@pytest.mark.parametrize('wrong_voice', [False, True])
def test_fake_service_explicit_profile_high_qos_and_two_warmups_before_listener(monkeypatch, tmp_path, wrong_voice):
    production = tmp_path/'production'; production.mkdir()
    marker = production/'profile-marker'; marker.write_bytes(b'synthetic-not-private')
    output = tmp_path/'output'; output.mkdir()
    order, events, captured = [], [], {}
    class Store:
        def __init__(self, root):
            assert root == production
            self.profile_path = marker
        def profile(self):return {}, 'config'
        def model_context(self):return {}, None, 'context'
    class Synth:
        def __init__(self, source, model, **kwargs):
            order.append('construct'); captured.update(kwargs)
            assert source == production/'local/runtime/CosyVoice'
            fake.configure_runtime_cache()
            self.runtime_info = {}
            self._generate('existing default warmup')
        def _generate(self, _text, _context):return b'synthetic'
        def stream_chunks(self, _text, **_kwargs):yield b'synthetic'
        def prepare_selected_voice(self):
            order.append('selected_warmup'); self.selected_warmup_identity = 'context'
            list(self.stream_chunks('existing selected warmup', use_cache=False, model_streaming=True))
    class Server:
        def __init__(self, addr, synth):
            order.append('bind'); assert addr == ('127.0.0.1', 18774); self.synth = synth
        def shutdown(self):pass
        def serve_forever(self, **kwargs):
            assert self.synth._window_measurements_ready
        def server_close(self):order.append('close')
    fake = SimpleNamespace(__file__=str(PATH.with_name('service.py')), CosyVoiceSynthesizer=Synth,
        CosyVoiceHTTPServer=Server, _trial=SimpleNamespace(install_modelscope_offline=lambda: None),
        backend_capabilities=lambda _: {'audio_stream': {'incremental_usable': True,
            'profile_identity': dict(config_digest='wrong-default' if wrong_voice else 'config',
                context_digest='context', state='valid', selected_voice_warm=True)}})
    monkeypatch.setitem(sys.modules, 'service', fake)
    monkeypatch.setitem(sys.modules, 'voice_profiles', SimpleNamespace(VoiceProfileStore=Store))
    monkeypatch.setitem(sys.modules, 'windows_qos', SimpleNamespace(
        apply_current_process_high_qos=lambda: order.append('qos') or {'applied': True}))
    monkeypatch.setattr(sys, 'path', sys.path[:])
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'stop\n')))
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    monkeypatch.setattr(w.os.path, 'relpath', lambda *_: '../../../runtime/modelscope-cache')
    actual_loader = w.load_module
    monkeypatch.setattr(w, 'load_module', lambda name, path: (
        SimpleNamespace(image_identity=lambda _: {'pid': 123, 'creation_token': 'fake', 'executable_path': 'fake'})
        if name == 'ai_window_worker_identity' else actual_loader(name, path)))
    if wrong_voice:
        with pytest.raises(w.WindowStopped, match='not_matching_current'):
            w.start_model_service({'production_root': str(production), 'output': str(output)}, events.append)
        assert 'bind' not in order
        return
    w.start_model_service({'production_root': str(production), 'output': str(output)}, events.append)
    assert captured == dict(profile_root=production, hidden_only=True, model_streaming=False,
                            force_buffered_audio=False, warm_selected_voice=False)
    assert order == ['qos', 'construct', 'selected_warmup', 'bind', 'close']
    assert [x['event'] for x in events if x['event'] != 'stage'] == ['warmup_begin', 'warmup_complete', 'warmup_begin', 'warmup_complete', 'service_ready']
    assert marker.read_bytes() == b'synthetic-not-private'


@pytest.mark.skipif(os.name != 'nt', reason='Windows owned Job CPU process test')
def test_real_job_cleans_only_own_cpu_process_and_descendant():
    owner = w.load_module('ai_window_cpu_job_test', ROOT/'scripts/development/launcher/winjob.py')
    job = owner.Job()
    process = None
    code = "import sys,json,subprocess,time; json.loads(sys.stdin.buffer.readline()); child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(json.dumps({'event':'cpu_ready','child':child.pid}),flush=True); time.sleep(60)"
    try:
        process = w.spawn_owned([sys.executable, '-B', '-c', code], job, payload={}, stdout=subprocess.PIPE)
        events = w.ServiceEvents(process)
        value = events.get(5)
        assert value['event'] == 'cpu_ready' and value['child'] > 0
    finally:
        job.close()  # 内部已核对自有Job active==0，包含后代。
        if process is not None:
            process.wait(timeout=2)
            process.stdin.close(); process.stdout.close()
    assert process.poll() is not None
