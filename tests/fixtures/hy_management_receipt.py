"""离线管理验收回执工具；回执不是密码学签名，也不替代代码审查。

旧模式要求背景语义写关闭；managed-semantic模式固定验收受管写与派生失效。
两者均须精确源码清洁且真实SDK测试零跳过后才签发。
不修改正式配置；全部新证据只写工具仓库data/test-tmp下的排他目录。
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hy_campus_latency_probe as probe


TOOL_ROOT = Path(__file__).resolve().parents[2]
TESTS = ('tests/integration/test_hy_memory_management_rpc.py',
         'tests/integration/test_hy_release_management.py')
SEMANTIC_TESTS = (*TESTS,
    'tests/integration/test_hy_layer_data_sdk.py',
    'tests/integration/test_hy_semantic_sdk.py',
    'tests/integration/test_ab_hy_provenance_replay.py',
    'tests/integration/test_hy_semantic_platform_sdk.py',
    'tests/integration/test_hy_background_sdk.py',
    'tests/integration/test_hy_background_gateway_combination.py',
    'tests/integration/test_voice_proposal_sdk_rpc.py',
    'tests/unit/development/test_voice_proposal_sdk_input.py',
    'tests/unit/development/test_voice_proposal_rpc.py',
    'tests/integration/test_voice_proposal_routes.py',
    'tests/integration/test_hy_semantic_platform.py',
    'tests/unit/application/test_managed_memory_proposals.py',
    'tests/unit/application/test_owned_background_bootstrap.py',
    'tests/unit/methods/test_hy_provenance.py',
    'tests/unit/methods/test_hy_semantic_cold.py',
    'tests/unit/methods/test_hy_model_admission.py',
    *(f'tests/integration/test_hy_daily_lifecycle.py::{name}' for name in (
        'test_constant_identity_restart_shared_spend_and_owned_gateway_cleanup',
        'test_initialization_failure_releases_gateway_and_preserves_budget',
        'test_currency_proof_for_another_credential_cannot_start_or_charge',
        'test_campus_free_runtime_restart_recall_preserves_official_unknown',
        'test_verified_daily_management_create_reopen_profile_scope_and_bad_receipt_cleanup',
        'test_preexisting_daily_space_does_not_gain_profile_proof_from_new_receipt',
        'test_daily_requested_profile_injection_without_scope_fails_and_closes_owned_gateway')))
REQUIRED_SEMANTIC_CASES = {
    'test_real_process_management_permissions_update_delete_and_restart',
    'test_real_native_evolve_graph_content_sources_restart_and_readonly_intention',
    'test_real_unverified_profile_intention_formal_candidate_labels_and_batch_capture_diagnostics',
    'test_real_runtime_management_readback_then_rederive_preserves_correction_sources',
    'test_real_pro_source_enable_semantic_reopen_rollback_preserves_source_graph_and_tasks',
    'test_real_sdk_formal_routes_and_python310_preserve_effective_input',
}
BOOTSTRAP = """import os,subprocess,sys
# Windows execv会结束包装进程；保持此Job根存活，等待真实目标并传回其退出码。
if os.read(sys.stdin.fileno(),1)!=b'1':
    sys.exit(97)
# 许可只用原始读取；余下配置在本进程读完并显式转发，避免缓冲预读丢字节。
payload=sys.stdin.buffer.read(262145)
if len(payload)>262144:
    sys.exit(98)
result=subprocess.run(sys.argv[1:],input=payload,stdout=sys.stdout,stderr=sys.stderr,
                      close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
sys.exit(result.returncode)
"""
METADATA = ("import sys,json;from importlib.metadata import version;"
            "print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),'sdk':version('hy-memory')}))")


class ReceiptFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ReceiptFailure(code)


def new_job():
    require(os.name == 'nt', 'management_windows_job_required')
    path = probe.unlinked(TOOL_ROOT / 'scripts/development/launcher/winjob.py')
    specification = importlib.util.spec_from_file_location('management_receipt_owned_job', path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.Job()


def owned_run(command, *, cwd, env, timeout, capture=False, input_bytes=b'', log_path=None):
    """先等待许可，加入Job后启动并等待真实目标；任何退出均回收全部后代。"""
    require(type(input_bytes) is bytes and len(input_bytes) <= 262144, 'management_runner_input_limit')
    try:
        job = new_job()
    except Exception:
        raise ReceiptFailure('management_job_unavailable') from None
    process = log = None
    try:
        if log_path is not None:
            require(not capture, 'management_runner_log_capture_conflict')
            log = Path(log_path).open('xb')
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', '-c', BOOTSTRAP, *map(str, command)],
            cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture else log if log is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if log is not None else subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        job.assign(process)
        output, _ = process.communicate(b'1' + input_bytes, timeout=timeout)
        output = output or b''
        require(len(output) <= 65536, 'management_runner_output_limit')
        return process.returncode, output
    except subprocess.TimeoutExpired:
        raise ReceiptFailure('management_runner_timeout') from None
    except ReceiptFailure:
        raise
    except Exception:
        raise ReceiptFailure('management_runner_failed') from None
    finally:
        failed = False
        try:
            job.close()
        except Exception:
            failed = True
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            except Exception:
                failed = True
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        if log is not None:
            log.close()
        if failed:
            raise ReceiptFailure('management_owned_exit_unconfirmed') from None


def clean_environment():
    result = {key: value for key, value in os.environ.items() if key.upper() in
              {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}}
    result.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
        ANONYMIZED_TELEMETRY='False', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    return result


def require_ignored(output):
    result = subprocess.run(['git', '-C', str(TOOL_ROOT), 'check-ignore', '--quiet', '--', str(output)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    require(result.returncode == 0, 'management_output_not_ignored')


def junit_count(path):
    path = probe.unlinked(path)
    require(path.is_file() and path.stat().st_size <= 16_000_000, 'management_junit_missing_or_large')
    body = path.read_bytes()
    require(b'<!DOCTYPE' not in body.upper(), 'management_junit_invalid')
    try:
        root = ET.fromstring(body)
        require(root.tag in {'testsuite', 'testsuites'}, 'management_junit_invalid')
        for suite in root.iter():
            if suite.tag in {'testsuite', 'testsuites'}:
                for key in ('failures', 'errors', 'skipped'):
                    require(int(suite.attrib.get(key, '0')) == 0, 'management_tests_not_all_passed')
        require(not list(root.iter('failure')) and not list(root.iter('error'))
                and not list(root.iter('skipped')), 'management_tests_not_all_passed')
        count = len(list(root.iter('testcase')))
        require(count > 0, 'management_no_testcases')
        return count, probe.digest(body)
    except (ET.ParseError, ValueError):
        raise ReceiptFailure('management_junit_invalid') from None


def run(arguments):
    semantic = getattr(arguments, 'managed_semantic', False)
    require(type(semantic) is bool, 'management_mode_invalid')
    reviewed = arguments.reviewed_semantic_background_writes_disabled
    require((semantic and reviewed is False) or (not semantic and reviewed is True),
            'management_explicit_review_required')
    tests = SEMANTIC_TESTS if semantic else TESTS
    require(isinstance(arguments.expected_head, str) and re.fullmatch(r'[0-9a-f]{40}', arguments.expected_head),
            'management_full_head_required')
    root, sdk = probe.unlinked(arguments.source_root), probe.unlinked(arguments.sdk_python)
    output = probe.validate_output(arguments.output, TOOL_ROOT / 'data/test-tmp')
    require_ignored(output)
    require(sdk.is_file(), 'management_sdk_missing')
    require(all((root / name.split('::')[0]).is_file() for name in tests), 'management_test_source_missing')
    voice = capture = None
    if semantic:
        require(getattr(arguments, 'voice_python', None) is not None and getattr(arguments, 'capture', None) is not None,
                'management_semantic_inputs_required')
        voice, capture = probe.unlinked(arguments.voice_python), probe.unlinked(arguments.capture)
        require(voice.is_file() and capture.is_dir(), 'management_semantic_inputs_missing')
    before = probe.source_identity(root)
    require(before['head'] == arguments.expected_head, 'management_head_mismatch')
    rpc_identity = probe.management_identity(root)
    sdk_hash = probe.digest(sdk.read_bytes())
    code, data = owned_run([sdk, '-I', '-B', '-X', 'utf8', '-c', METADATA],
                           cwd=root, env=clean_environment(), timeout=20, capture=True)
    try:
        metadata = json.loads(data)
    except (ValueError, UnicodeError):
        raise ReceiptFailure('management_sdk_metadata_invalid') from None
    require(code == 0 and metadata == {'python': '3.12.13', 'sdk': '2.0.3'}, 'management_sdk_version_mismatch')
    voice_hash = None
    if semantic:
        voice_hash = probe.digest(voice.read_bytes())
        code, data = owned_run([voice, '-I', '-B', '-X', 'utf8', '-c',
            "import sys,json;print(json.dumps('.'.join(map(str,sys.version_info[:3]))))"],
            cwd=root, env=clean_environment(), timeout=20, capture=True)
        require(code == 0 and data.strip() == b'"3.10.20"', 'management_voice_version_mismatch')
    # SDK元数据核验失败时不创建输出。真正验收一旦开始，失败证据一律保留。
    output.mkdir(parents=True, exist_ok=False)
    # 生命周期夹具保留历史部署的深层相对路径。把pytest放在长回执目录内，
    # Windows SQLite的journal路径可能越界；短且排他的目录仍只位于本工具树。
    scratch = output / 'pytest'
    if semantic:
        scratch = probe.validate_output(TOOL_ROOT / 'data/test-tmp' / ('mr-' + secrets.token_hex(4)), TOOL_ROOT / 'data/test-tmp')
        require_ignored(scratch)
    home = output / 'home'
    home.mkdir()
    env = clean_environment()
    env.update(HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
        HF_HOME=str(home / 'huggingface'), XDG_CACHE_HOME=str(home / 'cache'),
        PYTHONPATH=str(root / 'src'), LONGMEMORY_TEST_HY_PYTHON=str(sdk))
    if semantic:
        env.update(LONGMEMORY_TEST_PY310=str(voice), LONGMEMORY_TEST_AB_CAPTURE=str(capture),
            LONGMEMORY_TEST_VOICE_HOST_REF=before['head'], LONGMEMORY_TEST_SDK_HOST_REF=before['head'])
    junit = output / 'junit.xml'
    receipt = {'version': 1, 'kind': 'verification_receipt_not_cryptographic_signature',
        'source': before, 'sdk_python_sha256': sdk_hash, 'sdk_python_version': metadata['python'],
        'sdk_version': metadata['sdk'], 'rpc_source_sha256': rpc_identity,
        'semantic_background_writes_reviewed_by_caller': not semantic, 'status': 'failed',
        'test_count': 0, 'junit_sha256': None, 'error': None}
    if semantic:
        receipt.update(management_protocol=2, semantic_background_writes='managed_v1',
            voice_python_version='3.10.20', voice_python_sha256=voice_hash, test_paths=list(tests),
            pytest_basetemp=scratch.relative_to(TOOL_ROOT).as_posix())
    try:
        command = [sys.executable, '-B', '-X', 'utf8', '-m', 'pytest', *tests, '-q',
                   '--basetemp', str(scratch), '--junitxml', str(junit)]
        code, _ = owned_run(command, cwd=root, env=env, timeout=900 if semantic else 300,
            **({'log_path': output / 'pytest.log'} if semantic else {}))
        require(code == 0, 'management_pytest_failed')
        count, junit_hash = junit_count(junit)
        receipt.update(test_count=count, junit_sha256=junit_hash)
        if semantic:
            names = {case.attrib.get('name', '').split('[')[0] for case in ET.parse(junit).iter('testcase')}
            require(REQUIRED_SEMANTIC_CASES <= names, 'management_required_semantic_cases_missing')
            require(probe.digest(voice.read_bytes()) == voice_hash, 'management_voice_changed')
            receipt['pytest_log_sha256'] = probe.digest((output / 'pytest.log').read_bytes())
        require(probe.source_identity(root) == before and probe.management_identity(root) == rpc_identity
            and probe.digest(sdk.read_bytes()) == sdk_hash, 'management_source_or_sdk_changed')
        receipt['status'] = 'completed'
        probe.write_new(output / 'receipt.json', receipt)
        proof = {
            'sdk_version': '2.0.3', 'rpc_source_sha256': rpc_identity,
            'real_sdk_rpc_verified': True}
        proof.update({'protocol': 2, 'semantic_background_writes': 'managed_v1',
            'derivation_invalidation_verified': True, 'read_only_intention_verified': True} if semantic else
            {'semantic_background_writes_disabled': True})
        probe.write_new(output / 'management-verification.json', proof)
        return receipt
    except BaseException as error:
        receipt['error'] = ('management_cancelled' if isinstance(error, KeyboardInterrupt)
            else str(error) if isinstance(error, ReceiptFailure) else 'management_validation_failed')
        if not (output / 'receipt.json').exists():
            probe.write_new(output / 'receipt.json', receipt)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'sdk-python', 'output'):
        parser.add_argument('--' + name, required=True, type=lambda value: Path(value).absolute())
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--reviewed-semantic-background-writes-disabled', action='store_true')
    parser.add_argument('--managed-semantic', action='store_true', help='固定完整受管语义/来源/后台/跨Python回归，生成协议2候选')
    parser.add_argument('--voice-python', type=lambda value: Path(value).absolute())
    parser.add_argument('--capture', type=lambda value: Path(value).absolute())
    arguments = parser.parse_args()
    try:
        receipt = run(arguments)
    except BaseException as error:
        code = ('management_cancelled' if isinstance(error, KeyboardInterrupt)
            else str(error) if isinstance(error, ReceiptFailure) else 'management_receipt_refused')
        print(json.dumps({'status': 'refused', 'error': code}))
        raise SystemExit(2)
    print(json.dumps({'status': 'completed', 'test_count': receipt['test_count'],
                      'source_head': receipt['source']['head'], 'junit_sha256': receipt['junit_sha256']}))


if __name__ == '__main__':
    main()
