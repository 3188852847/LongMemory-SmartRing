"""模拟runner验证离线回执门控；本文件不运行实际SDK或集成测试。"""

from io import BytesIO
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
SPEC = importlib.util.spec_from_file_location('isolated_management_receipt', ROOT / 'tests/fixtures/hy_management_receipt.py')
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)
HEAD = 'a' * 40
IDENTITY = {'head': HEAD, 'tree': 'b' * 40, 'python_source_sha256': 'c' * 64}
RPC = 'd' * 64
PASSING = '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="one"/><testcase name="two"/></testsuite></testsuites>'


@pytest.fixture
def arranged(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    for name in receipt.TESTS:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('# synthetic test placeholder', encoding='utf-8')
    sdk = tmp_path / 'sdk-python.exe'
    sdk.write_bytes(b'synthetic executable, never executed')
    output = tmp_path / 'data/test-tmp/unique-receipt'
    arguments = SimpleNamespace(source_root=source, sdk_python=sdk, output=output,
        expected_head=HEAD, reviewed_semantic_background_writes_disabled=True)
    state = SimpleNamespace(calls=[], metadata={'python': '3.12.13', 'sdk': '2.0.3'},
                            junit=PASSING, code=0, error=None, after_tests=None)
    monkeypatch.setattr(receipt, 'TOOL_ROOT', tmp_path)
    monkeypatch.setattr(receipt, 'require_ignored', lambda path: None)
    monkeypatch.setattr(receipt.probe, 'source_identity', lambda root: dict(IDENTITY))
    monkeypatch.setattr(receipt.probe, 'management_identity', lambda root: RPC)
    def runner(command, **kwargs):
        state.calls.append((command, kwargs))
        if kwargs.get('capture'):
            return 0, json.dumps(state.metadata).encode()
        if state.error is not None:
            raise state.error
        junit = Path(command[command.index('--junitxml') + 1])
        if state.junit is not None:
            junit.write_text(state.junit, encoding='utf-8')
        if state.after_tests is not None:
            state.after_tests()
        return state.code, b''
    monkeypatch.setattr(receipt, 'owned_run', runner)
    return arguments, state


def test_success_issues_exact_four_field_proof_and_metadata_receipt(arranged):
    arguments, state = arranged
    result = receipt.run(arguments)
    assert result['status'] == 'completed' and result['test_count'] == 2
    proof = json.loads((arguments.output / 'management-verification.json').read_text())
    assert proof == {'sdk_version': '2.0.3', 'rpc_source_sha256': RPC,
        'real_sdk_rpc_verified': True, 'semantic_background_writes_disabled': True}
    saved = json.loads((arguments.output / 'receipt.json').read_text())
    assert saved['source'] == IDENTITY and saved['sdk_python_sha256'] == receipt.probe.digest(arguments.sdk_python.read_bytes())
    assert saved['junit_sha256'] == receipt.probe.digest((arguments.output / 'junit.xml').read_bytes())
    assert saved['kind'] == 'verification_receipt_not_cryptographic_signature'
    command, options = state.calls[1]
    assert command[:7] == [sys.executable, '-B', '-X', 'utf8', '-m', 'pytest', receipt.TESTS[0]]
    assert receipt.TESTS[1] in command and options['cwd'] == arguments.source_root
    assert options['env']['PYTHONPATH'] == str(arguments.source_root / 'src')
    assert options['env']['LONGMEMORY_TEST_HY_PYTHON'] == str(arguments.sdk_python)
    assert Path(command[command.index('--basetemp') + 1]).is_relative_to(arguments.output)
    assert state.calls[0][0][1:5] == ['-I', '-B', '-X', 'utf8']
    assert 'import hy_memory' not in state.calls[0][0][-1]
    assert 'credential' not in json.dumps(saved) and 'body' not in json.dumps(saved)


@pytest.mark.parametrize('field,value,code', [('reviewed_semantic_background_writes_disabled', False, 'management_explicit_review_required'),
    ('expected_head', 'a' * 7, 'management_full_head_required'), ('expected_head', 'f' * 40, 'management_head_mismatch')])
def test_missing_review_or_wrong_head_refuses_before_execution(arranged, field, value, code):
    arguments, state = arranged
    setattr(arguments, field, value)
    with pytest.raises(receipt.ReceiptFailure, match='^' + code + '$'):
        receipt.run(arguments)
    assert state.calls == [] and not arguments.output.exists()


def test_dirty_source_refuses_without_runner_or_output(arranged, monkeypatch):
    arguments, state = arranged
    def dirty(root):
        raise receipt.probe.ProbeFailure('probe_source_not_clean')
    monkeypatch.setattr(receipt.probe, 'source_identity', dirty)
    with pytest.raises(receipt.probe.ProbeFailure, match='source_not_clean'):
        receipt.run(arguments)
    assert state.calls == [] and not arguments.output.exists()


def test_output_reuse_cannot_overwrite_evidence(arranged):
    arguments, state = arranged
    arguments.output.mkdir(parents=True)
    original = arguments.output / 'receipt.json'
    original.write_bytes(b'prior evidence')
    with pytest.raises(receipt.probe.ProbeFailure, match='new_output_required'):
        receipt.run(arguments)
    assert original.read_bytes() == b'prior evidence' and not state.calls


@pytest.mark.parametrize('metadata', [{'python': '3.12.12', 'sdk': '2.0.3'},
    {'python': '3.12.13', 'sdk': '2.0.4'}, {'python': '3.12.13', 'sdk': '2.0.3', 'extra': True}])
def test_actual_sdk_metadata_must_match_exact_versions(arranged, metadata):
    arguments, state = arranged
    state.metadata = metadata
    with pytest.raises(receipt.ReceiptFailure, match='management_sdk_version_mismatch'):
        receipt.run(arguments)
    assert len(state.calls) == 1 and not arguments.output.exists()


@pytest.mark.parametrize('xml,code', [
    ('<testsuite tests="1" skipped="1"><testcase><skipped/></testcase></testsuite>', 'management_tests_not_all_passed'),
    ('<testsuite tests="1" skipped="0"><testcase><skipped/></testcase></testsuite>', 'management_tests_not_all_passed'),
    ('<testsuite tests="1" failures="0"><testcase><failure/></testcase></testsuite>', 'management_tests_not_all_passed'),
    ('<testsuite tests="1" errors="1"><testcase><error/></testcase></testsuite>', 'management_tests_not_all_passed'),
    ('<testsuite tests="0"/>', 'management_no_testcases'), ('not xml', 'management_junit_invalid'),
    ('<!DOCTYPE x><testsuite/>', 'management_junit_invalid')])
def test_skip_failure_error_zero_cases_and_malformed_junit_never_issue_proof(arranged, xml, code):
    arguments, state = arranged
    state.junit = xml
    with pytest.raises(receipt.ReceiptFailure, match='^' + code + '$'):
        receipt.run(arguments)
    assert not (arguments.output / 'management-verification.json').exists()
    assert (arguments.output / 'junit.xml').read_text() == xml
    assert json.loads((arguments.output / 'receipt.json').read_text())['status'] == 'failed'


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'cancelled'])
def test_runner_failure_preserves_failed_receipt_without_issuing_proof(arranged, failure):
    arguments, state = arranged
    if failure == 'exit': state.code = 1
    elif failure == 'timeout': state.error = receipt.ReceiptFailure('management_runner_timeout')
    else: state.error = KeyboardInterrupt()
    with pytest.raises((receipt.ReceiptFailure, KeyboardInterrupt)):
        receipt.run(arguments)
    assert not (arguments.output / 'management-verification.json').exists()
    saved = json.loads((arguments.output / 'receipt.json').read_text())
    assert saved['status'] == 'failed'
    if failure == 'cancelled': assert saved['error'] == 'management_cancelled'


def test_source_change_after_tests_prevents_proof(arranged, monkeypatch):
    arguments, state = arranged
    identities = iter((dict(IDENTITY), {**IDENTITY, 'head': 'f' * 40}))
    monkeypatch.setattr(receipt.probe, 'source_identity', lambda root: next(identities))
    with pytest.raises(receipt.ReceiptFailure, match='management_source_or_sdk_changed'):
        receipt.run(arguments)
    assert not (arguments.output / 'management-verification.json').exists()
    assert (arguments.output / 'junit.xml').exists()


@pytest.mark.parametrize('change', ['rpc', 'sdk', 'missing_junit'])
def test_rpc_sdk_changes_and_missing_report_refuse_proof(arranged, monkeypatch, change):
    arguments, state = arranged
    if change == 'rpc':
        values = iter((RPC, 'f' * 64))
        monkeypatch.setattr(receipt.probe, 'management_identity', lambda root: next(values))
    elif change == 'sdk':
        state.after_tests = lambda: arguments.sdk_python.write_bytes(b'changed synthetic executable')
    else:
        state.junit = None
    with pytest.raises(receipt.ReceiptFailure):
        receipt.run(arguments)
    assert not (arguments.output / 'management-verification.json').exists()
    assert json.loads((arguments.output / 'receipt.json').read_text())['status'] == 'failed'


def test_output_outside_owned_test_root_is_refused(arranged):
    arguments, state = arranged
    arguments.output = arguments.source_root / 'local/config/forbidden-receipt'
    with pytest.raises(receipt.probe.ProbeFailure, match='new_output_required'):
        receipt.run(arguments)
    assert not state.calls and not arguments.output.exists()


def test_environment_does_not_inherit_private_selection_or_proxy_values(monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'synthetic-private-proxy')
    monkeypatch.setenv('LONGMEMORY_LLM_API_KEY', 'synthetic-private-key')
    monkeypatch.setenv('LONGMEMORY_TEST_HY_PYTHON', 'unreviewed-sdk')
    env = receipt.clean_environment()
    assert 'HTTP_PROXY' not in env and 'LONGMEMORY_LLM_API_KEY' not in env
    assert 'LONGMEMORY_TEST_HY_PYTHON' not in env
    assert env['PYTHON_DOTENV_DISABLED'] == env['HF_HUB_OFFLINE'] == env['TRANSFORMERS_OFFLINE'] == '1'


def test_ignored_output_check_is_required_before_version_probe(arranged, monkeypatch):
    arguments, state = arranged
    def not_ignored(output):
        raise receipt.ReceiptFailure('management_output_not_ignored')
    monkeypatch.setattr(receipt, 'require_ignored', not_ignored)
    with pytest.raises(receipt.ReceiptFailure, match='management_output_not_ignored'):
        receipt.run(arguments)
    assert not state.calls and not arguments.output.exists()


@pytest.mark.parametrize('mode', ['success', 'assign_failure', 'timeout', 'cancelled', 'cleanup_failure'])
def test_owned_runner_assigns_job_before_releasing_stdin_and_always_reaps(monkeypatch, tmp_path, mode):
    events = []
    class Job:
        def assign(self, process):
            events.append('assign')
            if mode == 'assign_failure': raise OSError('synthetic ownership failure')
        def close(self):
            events.append('close_job')
            if mode == 'cleanup_failure': raise OSError('synthetic cleanup failure')
    class Process:
        def __init__(self, command, **kwargs):
            self.stdin, self.stdout = BytesIO(), BytesIO()
            self.returncode = None
            events.append('popen')
            assert 'os.read(sys.stdin.fileno(),1)' in command[6]
            assert 'subprocess.run' in command[6] and 'sys.exit(result.returncode)' in command[6]
            assert kwargs['env'] == {'SYNTHETIC': '1'}
        def communicate(self, permit, timeout):
            events.append('permit')
            assert events.index('assign') < events.index('permit') and permit == b'1'
            if mode == 'timeout': raise subprocess.TimeoutExpired('synthetic', timeout)
            if mode == 'cancelled': raise KeyboardInterrupt()
            self.returncode = 0
            return b'{}', None
        def poll(self): return self.returncode
        def kill(self): events.append('kill_parent'); self.returncode = 1
        def wait(self, timeout): events.append('wait_parent'); return self.returncode
    monkeypatch.setattr(receipt, 'new_job', Job)
    monkeypatch.setattr(receipt.subprocess, 'Popen', Process)
    if mode == 'success':
        assert receipt.owned_run(['synthetic-python', '-m', 'pytest'], cwd=tmp_path,
                                 env={'SYNTHETIC': '1'}, timeout=1, capture=True) == (0, b'{}')
    else:
        with pytest.raises((receipt.ReceiptFailure, KeyboardInterrupt)):
            receipt.owned_run(['synthetic-python'], cwd=tmp_path, env={'SYNTHETIC': '1'}, timeout=1)
    assert events.count('close_job') == 1 and events.count('wait_parent') == 1
    if mode == 'assign_failure': assert 'permit' not in events and 'kill_parent' in events
    if mode in {'timeout', 'cancelled'}:
        assert events.index('close_job') < events.index('kill_parent')


def test_job_creation_failure_never_starts_a_process(monkeypatch, tmp_path):
    def unavailable(): raise OSError('synthetic no ownership permission')
    monkeypatch.setattr(receipt, 'new_job', unavailable)
    monkeypatch.setattr(receipt.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('must not spawn'))
    with pytest.raises(receipt.ReceiptFailure, match='management_job_unavailable'):
        receipt.owned_run(['synthetic-python'], cwd=tmp_path, env={}, timeout=1)


@pytest.fixture
def semantic_arranged(arranged, monkeypatch):
    arguments, state = arranged
    arguments.managed_semantic = True
    arguments.reviewed_semantic_background_writes_disabled = False
    arguments.voice_python = arguments.sdk_python.parent / 'voice-python.exe'
    arguments.voice_python.write_bytes(b'synthetic voice interpreter, never executed')
    arguments.capture = arguments.sdk_python.parent / 'capture'
    arguments.capture.mkdir()
    for entry in receipt.SEMANTIC_TESTS:
        target = arguments.source_root / entry.split('::')[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('# synthetic fixed suite', encoding='utf-8')
    names = sorted(receipt.REQUIRED_SEMANTIC_CASES)
    state.junit = '<testsuite tests="6">' + ''.join(f'<testcase name="{name}"/>' for name in names) + '</testsuite>'
    def runner(command, **kwargs):
        state.calls.append((command, kwargs))
        if kwargs.get('capture'):
            return 0, (b'"3.10.20"' if command[0] == arguments.voice_python else json.dumps(state.metadata).encode())
        Path(kwargs['log_path']).write_bytes(b'synthetic test log')
        Path(command[command.index('--junitxml') + 1]).write_text(state.junit, encoding='utf-8')
        if state.after_tests:
            state.after_tests()
        return state.code, b''
    monkeypatch.setattr(receipt, 'owned_run', runner)
    return arguments, state


def test_semantic_mode_requires_fixed_suite_and_generates_exact_v2_after_tests(semantic_arranged):
    arguments, state = semantic_arranged
    result = receipt.run(arguments)
    assert result['status'] == 'completed' and result['management_protocol'] == 2
    proof = json.loads((arguments.output / 'management-verification.json').read_text())
    assert proof == {'protocol': 2, 'sdk_version': '2.0.3', 'rpc_source_sha256': RPC,
        'real_sdk_rpc_verified': True, 'semantic_background_writes': 'managed_v1',
        'derivation_invalidation_verified': True, 'read_only_intention_verified': True}
    command, options = state.calls[-1]
    assert all(entry in command for entry in receipt.SEMANTIC_TESTS)
    assert result['test_paths'] == list(receipt.SEMANTIC_TESTS) and options['timeout'] == 900
    assert options['env']['LONGMEMORY_TEST_VOICE_HOST_REF'] == HEAD
    assert options['env']['LONGMEMORY_TEST_SDK_HOST_REF'] == HEAD
    assert options['env']['LONGMEMORY_TEST_PY310'] == str(arguments.voice_python)
    assert options['env']['LONGMEMORY_TEST_AB_CAPTURE'] == str(arguments.capture)
    assert result['pytest_log_sha256'] == receipt.probe.digest(b'synthetic test log')
    scratch = Path(command[command.index('--basetemp') + 1])
    assert scratch.parent == receipt.TOOL_ROOT / 'data/test-tmp'
    assert scratch.name.startswith('mr-') and len(scratch.name) == 11
    assert not scratch.is_relative_to(arguments.output)
    assert result['pytest_basetemp'] == scratch.relative_to(receipt.TOOL_ROOT).as_posix()


@pytest.mark.parametrize('change,code', [
    ('review', 'management_explicit_review_required'),
    ('missing_voice', 'management_semantic_inputs_required'),
    ('missing_capture', 'management_semantic_inputs_missing'),
    ('missing_case', 'management_required_semantic_cases_missing'),
    ('voice_changed', 'management_voice_changed')])
def test_semantic_mode_never_issues_proof_on_incomplete_evidence(semantic_arranged, change, code):
    arguments, state = semantic_arranged
    if change == 'review': arguments.reviewed_semantic_background_writes_disabled = True
    elif change == 'missing_voice': arguments.voice_python = None
    elif change == 'missing_capture': arguments.capture = arguments.capture / 'missing'
    elif change == 'missing_case': state.junit = PASSING
    else: state.after_tests = lambda: arguments.voice_python.write_bytes(b'changed voice executable')
    with pytest.raises(receipt.ReceiptFailure, match='^' + code + '$'):
        receipt.run(arguments)
    assert not (arguments.output / 'management-verification.json').exists()
