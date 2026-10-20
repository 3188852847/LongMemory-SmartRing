"""独立双源码/实际SDK只接本地合成上游；不访问学校/私有配置/真实BGE。"""

from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import socket
from threading import Thread
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'tests/fixtures/hy_campus_latency_probe.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('isolated_campus_probe', SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
SDK = Path(os.environ.get('LONGMEMORY_TEST_HY_PYTHON', str(ROOT / 'local/runtime/hy-memory/.venv/Scripts/python.exe')))


def git(root, *arguments):
    return subprocess.check_output(['git', '-C', str(root), *arguments], stderr=subprocess.DEVNULL)


@pytest.fixture(scope='module')
def sources(tmp_path_factory):
    return source_snapshots(tmp_path_factory.mktemp('campus-source-snapshots'),
        (('baseline', '87a25e2'), ('candidate', 'ae53f729')))


@pytest.fixture(scope='module')
def current_sources(tmp_path_factory):
    # 父进程故障测试不比较模型/历史版本；浅检出仅承诺当前HEAD可归档。
    return source_snapshots(tmp_path_factory.mktemp('campus-current-snapshots'),
        (('baseline', 'HEAD'), ('candidate', 'HEAD')))


def source_snapshots(root, revisions):
    result = {}
    for name, revision in revisions:
        target = root / name
        target.mkdir()
        archived = git(ROOT, 'archive', '--format=zip', revision, 'src', 'scripts/development/xiaozhi')
        with zipfile.ZipFile(BytesIO(archived)) as archive:
            assert all(not Path(entry.filename).is_absolute() and '..' not in Path(entry.filename).parts for entry in archive.infolist())
            archive.extractall(target)
        git(target, 'init', '--quiet')
        git(target, 'add', '.')
        git(target, '-c', 'user.name=Synthetic Probe', '-c', 'user.email=synthetic@example.invalid',
            'commit', '--quiet', '-m', 'synthetic source snapshot')
        result[name] = target
    return result


@contextmanager
def upstream(mode='ok'):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            if mode == 'disconnect':
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if mode == 'http_error':
                data = b'{"error":"synthetic-private-diagnostic"}'
                self.send_response(500)
            elif body.get('stream'):
                rows = [{'choices': [{'delta': {'content': '合成用户喜欢无糖乌龙茶。'}}]}]
                if mode != 'missing_usage':
                    rows.append({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}})
                data = b''.join(b'data: ' + json.dumps(row, ensure_ascii=False).encode() + b'\r\n\r\n' for row in rows)
                data += b'data: [DONE]\r\n\r\n'
                self.send_response(200)
            else:
                content = json.dumps({'memory': [{'content': '合成用户喜欢无糖乌龙茶', 'tags': ['synthetic'], 'owner': 'user'}],
                                      'intentions': [], 'basic_info': {}}, ensure_ascii=False)
                data = json.dumps({'id': 'synthetic', 'model': 'DeepSeek-V4-Flash',
                    'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 3, 'total_tokens': 13}}, ensure_ascii=False).encode()
                self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Content-Type', 'text/event-stream' if body.get('stream') and mode != 'http_error' else 'application/json')
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server.server_port, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def owner_at(root, port):
    model, key = 'DeepSeek-V4-Flash', 'synthetic-campus-secret-never-print'
    endpoint = f'http://127.0.0.1:{port}/synthetic/v1'
    config = root / 'local/config'
    config.mkdir(parents=True)
    (config / '.env').write_text('\n'.join((
        'LONGMEMORY_LLM_BASE_URL=' + endpoint, 'LONGMEMORY_LLM_MODEL=' + model,
        'LONGMEMORY_LLM_API_KEY=' + key, 'LONGMEMORY_LLM_ALLOW_HTTP=true',
        'LONGMEMORY_LLM_TIMEOUT_SECONDS=5', 'LONGMEMORY_LLM_MAX_TOKENS=64')), encoding='utf-8')
    policy = {'version': 1, 'profile': 'campus', 'billing_mode': 'owner_confirmed_free', 'personal_cost_micro_cny': 0,
        'source': 'owner_confirmation', 'confirmed_date': '2026-10-19',
        'endpoint_sha256': sha256(endpoint.encode()).hexdigest(), 'request_model': model,
        'credential_sha256': sha256(key.encode()).hexdigest(), 'ledger_path': 'data/databases/never-open-owner-calls.db'}
    (config / 'hy-memory').mkdir()
    (config / 'hy-memory/provider-policy.json').write_text(json.dumps(policy), encoding='utf-8')
    return root


def arguments_at(tmp_path, sources, port, monkeypatch, *, limit=8):
    owner = owner_at(tmp_path / 'owner', port)
    for name in ('baseline', 'candidate'):
        proof = {'sdk_version': '2.0.3', 'rpc_source_sha256': probe.management_identity(sources[name]),
                 'real_sdk_rpc_verified': True, 'semantic_background_writes_disabled': True}
        (tmp_path / (name + '-proof.json')).write_text(json.dumps(proof), encoding='utf-8')
    # 输出边界仍由测试工作树的data/test-tmp控制，仅重绑定tool根为本夹具专有目录。
    monkeypatch.setattr(probe, 'TOOL_ROOT', tmp_path)
    # 子进程Job实现借用真实只读工具；不把测试目录伪装成业务源码。
    original = probe.child_process
    def child(config, **kwargs):
        old = probe.TOOL_ROOT
        probe.TOOL_ROOT = ROOT
        try: return original(config, **kwargs)
        finally: probe.TOOL_ROOT = old
    monkeypatch.setattr(probe, 'child_process', child)
    return SimpleNamespace(baseline_root=sources['baseline'], candidate_root=sources['candidate'], owner_root=owner,
        sdk_python=SDK.absolute(), baseline_proof=tmp_path / 'baseline-proof.json', candidate_proof=tmp_path / 'candidate-proof.json',
        output=tmp_path / 'data/test-tmp/new-run', mode='loopback', execute_campus=False,
        request_limit=limit, rounds_per_arm=2, arm_order='baseline,candidate', timeout_seconds=90)


def test_existing_output_and_linked_or_outside_paths_are_refused(tmp_path):
    allowed = tmp_path / 'data/test-tmp'
    allowed.mkdir(parents=True)
    with pytest.raises(probe.ProbeFailure): probe.validate_output(allowed, allowed)
    with pytest.raises(probe.ProbeFailure): probe.validate_output(tmp_path / 'elsewhere', allowed)
    existing = allowed / 'existing'
    existing.mkdir()
    with pytest.raises(probe.ProbeFailure): probe.validate_output(existing, allowed)


def test_source_fingerprint_rejects_dirty_and_untracked_code(tmp_path):
    (tmp_path / 'src/longmemory/methods/hy_memory').mkdir(parents=True)
    file = tmp_path / 'src/longmemory/methods/hy_memory/worker.py'
    file.write_text('# synthetic\n')
    git(tmp_path, 'init', '--quiet')
    git(tmp_path, 'add', '.')
    git(tmp_path, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '--quiet', '-m', 'test')
    identity = probe.source_identity(tmp_path)
    assert len(identity['python_source_sha256']) == 64
    file.write_text('# changed\n')
    with pytest.raises(probe.ProbeFailure, match='not_clean'): probe.source_identity(tmp_path)


def test_sse_partial_crlf_and_tool_delta_are_not_false_first_answer():
    sink = probe.AnswerSink()
    sink.write(b'data: {"choices":[{"delta":{"tool_calls":[]}}]}\r\n\r\n')
    assert sink.first_text_ms is None
    data = 'data: {"choices":[{"delta":{"content":"合成"}}]}\r\n\r\ndata: [DONE]\r\n\r\n'.encode()
    for byte in data: sink.write(bytes([byte]))
    assert sink.answer == '合成' and sink.done and sink.first_text_ms is not None


@pytest.mark.parametrize('limit', [0, 9, 100])
def test_out_of_bounds_limit_is_rejected_before_preflight(limit):
    with pytest.raises(probe.ProbeFailure, match='bounds_invalid'):
        probe.run(SimpleNamespace(request_limit=limit, rounds_per_arm=2))


@pytest.mark.skipif(not SDK.is_file(), reason='existing owner-installed SDK required; no installation')
def test_two_source_real_sdk_local_upstream_isolated_roots_and_safe_receipts(tmp_path, sources, monkeypatch):
    with upstream() as (port, calls):
        args = arguments_at(tmp_path, sources, port, monkeypatch)
        original = {p.relative_to(args.owner_root).as_posix(): p.read_bytes() for p in args.owner_root.rglob('*') if p.is_file()}
        receipt = probe.run(args)
        assert receipt['status'] == 'completed', (args.output / 'receipt.json').read_text()
        assert receipt['calls']['attempt_count'] == len(calls) <= 8
        assert receipt['calls']['unknown_or_inflight'] == 0
        assert receipt['completed_arms'] == ['baseline', 'candidate']
        for name in ('baseline', 'candidate'):
            arm = json.loads((args.output / (name + '-receipt.json')).read_text())
            assert len(arm['rounds']) == 2 and arm['rounds'][1]['prior_round_source_recalled']
            assert arm['rounds'][0]['completion'] == 'completed_and_extracted'
            assert arm['rounds'][1]['completion'] == 'cancelled_after_sampling'
        assert {p.relative_to(args.owner_root).as_posix(): p.read_bytes() for p in args.owner_root.rglob('*') if p.is_file()} == original
        public = '\n'.join(p.read_text() for p in args.output.glob('*.json'))
        assert 'synthetic-campus-secret-never-print' not in public and '合成用户喜欢' not in public
        assert not (args.owner_root / 'data').exists()
        with pytest.raises(probe.ProbeFailure): probe.run(args)


@pytest.mark.skipif(not SDK.is_file(), reason='existing owner-installed SDK required; no installation')
@pytest.mark.parametrize('mode', ['http_error', 'missing_usage', 'disconnect'])
def test_first_failure_or_unknown_stops_both_arms_without_retry(tmp_path, sources, monkeypatch, mode):
    with upstream(mode) as (port, calls):
        args = arguments_at(tmp_path, sources, port, monkeypatch)
        result = probe.run(args)
        assert result['status'] == 'failed' and result['calls']['halted']
        assert result['calls']['attempt_count'] == len(calls) == 1
        assert result['calls']['unknown_or_inflight'] == 1
        assert not (args.output / 'candidate').exists()


@pytest.mark.skipif(not SDK.is_file(), reason='existing owner-installed SDK required; no installation')
def test_hard_cap_blocks_extraction_after_first_answer_before_second_provider_post(tmp_path, sources, monkeypatch):
    with upstream() as (port, calls):
        args = arguments_at(tmp_path, sources, port, monkeypatch, limit=1)
        result = probe.run(args)
        assert result['status'] == 'failed' and result['calls']['halted']
        assert result['calls']['attempt_count'] == len(calls) == 1
        assert not (args.output / 'candidate').exists()


@pytest.mark.skipif(not SDK.is_file(), reason='existing owner-installed SDK required; no installation')
def test_bad_second_proof_refused_before_any_request_and_output_creation(tmp_path, sources, monkeypatch):
    with upstream() as (port, calls):
        args = arguments_at(tmp_path, sources, port, monkeypatch)
        bad = json.loads(args.candidate_proof.read_text())
        bad['rpc_source_sha256'] = '0' * 64
        args.candidate_proof.write_text(json.dumps(bad))
        with pytest.raises(probe.ProbeFailure, match='management_receipts'): probe.run(args)
        assert not calls and not args.output.exists()


@pytest.mark.parametrize('failure,reason', [(KeyboardInterrupt(), 'cancelled'),
    (subprocess.TimeoutExpired('synthetic-worker', 1), 'timeout'),
    (probe.ProbeFailure('probe_source_changed'), 'validation_failed')])
def test_parent_cancellation_timeout_or_source_change_halts_run_without_more_calls(tmp_path, current_sources, monkeypatch, failure, reason):
    with upstream() as (port, calls):
        args = arguments_at(tmp_path, current_sources, port, monkeypatch)
        # 此项在child边界注入故障，不执行SDK；preflight只需可指纹化的自有文件。
        args.sdk_python = tmp_path / 'synthetic-unused-python.exe'
        args.sdk_python.write_bytes(b'synthetic executable never launched')
        def stopped(*args, **kwargs): raise failure
        monkeypatch.setattr(probe, 'child_process', stopped)
        result = probe.run(args)
        assert result['status'] == 'failed' and result['error'] == reason
        assert result['calls']['halted'] and result['calls']['reason'] == reason
        assert result['calls']['attempt_count'] == 0 and not calls
        assert not (args.output / 'candidate').exists()


@pytest.mark.parametrize('kill_fails,stdin_close_fails', [(False, False), (True, False), (False, True)])
def test_job_close_failure_still_kills_waits_and_closes_each_pipe(tmp_path, monkeypatch, kill_fails, stdin_close_fails):
    events = []
    class Pipe:
        def __init__(self, name): self.name = name
        def close(self):
            events.append('close_' + self.name)
            if self.name == 'stdin' and stdin_close_fails:
                raise OSError('synthetic-private-pipe-detail')
    class Process:
        def __init__(self, *args, **kwargs):
            self.stdin, self.stdout = Pipe('stdin'), Pipe('stdout')
            self.returncode = None
            events.append('spawn')
        def communicate(self, data, timeout):
            events.append('communicate')
            raise subprocess.TimeoutExpired('synthetic-worker', timeout)
        def poll(self): return None
        def kill(self):
            events.append('kill')
            if kill_fails:
                raise OSError('synthetic-private-kill-detail')
        def wait(self, timeout): events.append('wait'); return 1
    class Job:
        def assign(self, process): events.append('assign')
        def close(self):
            events.append('job_close')
            raise OSError('synthetic-private-job-detail')
    fake_spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
    monkeypatch.setattr(probe, 'os', SimpleNamespace(name='nt', environ={}))
    monkeypatch.setattr(probe.importlib.util, 'spec_from_file_location', lambda *args: fake_spec)
    monkeypatch.setattr(probe.importlib.util, 'module_from_spec', lambda spec: SimpleNamespace(Job=Job))
    monkeypatch.setattr(probe.subprocess, 'Popen', Process)
    with pytest.raises(probe.ProbeFailure, match='^probe_owned_exit_unconfirmed$') as error:
        probe.child_process({'arm_directory': str(tmp_path)}, timeout=1)
    assert 'private' not in str(error.value)
    assert events == ['spawn', 'assign', 'communicate', 'job_close', 'kill', 'wait', 'close_stdin', 'close_stdout']


def test_job_close_failure_parent_halts_shared_ledger_without_second_arm(tmp_path, monkeypatch):
    identity = {'head': 'a' * 40, 'tree': 'b' * 40, 'python_source_sha256': 'c' * 64}
    policy = {'request_model': 'synthetic-only', 'ledger_path': 'calls.db'}
    config = {'identities': {name: identity for name in ('baseline', 'candidate')},
        'policy': policy, 'sdk_python_sha256': 'd' * 64, 'protected': {}, 'model_identity': {},
        'model': {}, 'prototype': {}, 'proofs': {'baseline': {}, 'candidate': {}}}
    arguments = SimpleNamespace(request_limit=8, rounds_per_arm=1, timeout_seconds=30,
        output=tmp_path / 'data/test-tmp/job-failure', arm_order='baseline,candidate', mode='loopback',
        baseline_root=tmp_path / 'baseline-source', candidate_root=tmp_path / 'candidate-source',
        owner_root=tmp_path / 'synthetic-owner', sdk_python=tmp_path / 'never-run-sdk.exe')
    monkeypatch.setattr(probe, 'TOOL_ROOT', tmp_path)
    monkeypatch.setattr(probe, 'preflight', lambda args: config)
    monkeypatch.setattr(probe, 'source_identity', lambda root: identity)
    visited = []
    def failed_child(configuration, *, timeout):
        visited.append(configuration['arm'])
        raise probe.ProbeFailure('probe_owned_exit_unconfirmed')
    monkeypatch.setattr(probe, 'child_process', failed_child)
    result = probe.run(arguments)
    assert visited == ['baseline'] and result['status'] == 'failed'
    assert result['error'] == 'probe_failed'
    assert result['calls']['halted'] and result['calls']['reason'] == 'probe_failed'
    assert result['calls']['attempt_count'] == 0
    assert not (arguments.output / 'candidate').exists()
