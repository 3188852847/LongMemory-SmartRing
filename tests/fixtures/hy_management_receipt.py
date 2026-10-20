"""离线管理验收回执工具；回执不是密码学签名，也不替代代码审查。

仅在调用者确认背景语义写关闭、精确源码清洁且真实SDK测试零跳过后签发。
不修改正式配置；全部新证据只写工具仓库data/test-tmp下的排他目录。
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hy_campus_latency_probe as probe


TOOL_ROOT = Path(__file__).resolve().parents[2]
TESTS = ('tests/integration/test_hy_memory_management_rpc.py',
         'tests/integration/test_hy_release_management.py')
BOOTSTRAP = ("import os,sys;permit=sys.stdin.buffer.read(1);"
             "sys.exit(97) if permit!=b'1' else None;os.execv(sys.argv[1],sys.argv[1:])")
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


def owned_run(command, *, cwd, env, timeout, capture=False):
    """先等待stdin，加入自有Job后才exec测试；任何退出均回收整棵后代树。"""
    try:
        job = new_job()
    except Exception:
        raise ReceiptFailure('management_job_unavailable') from None
    process = None
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', '-c', BOOTSTRAP, *map(str, command)],
            cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        job.assign(process)
        output, _ = process.communicate(b'1', timeout=timeout)
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
    require(type(arguments.reviewed_semantic_background_writes_disabled) is bool
        and arguments.reviewed_semantic_background_writes_disabled, 'management_explicit_review_required')
    require(isinstance(arguments.expected_head, str) and re.fullmatch(r'[0-9a-f]{40}', arguments.expected_head),
            'management_full_head_required')
    root, sdk = probe.unlinked(arguments.source_root), probe.unlinked(arguments.sdk_python)
    output = probe.validate_output(arguments.output, TOOL_ROOT / 'data/test-tmp')
    require_ignored(output)
    require(sdk.is_file(), 'management_sdk_missing')
    require(all((root / name).is_file() for name in TESTS), 'management_test_source_missing')
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
    # SDK元数据核验失败时不创建输出。真正验收一旦开始，失败证据一律保留。
    output.mkdir(parents=True, exist_ok=False)
    home = output / 'home'
    home.mkdir()
    env = clean_environment()
    env.update(HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
        HF_HOME=str(home / 'huggingface'), XDG_CACHE_HOME=str(home / 'cache'),
        PYTHONPATH=str(root / 'src'), LONGMEMORY_TEST_HY_PYTHON=str(sdk))
    junit = output / 'junit.xml'
    receipt = {'version': 1, 'kind': 'verification_receipt_not_cryptographic_signature',
        'source': before, 'sdk_python_sha256': sdk_hash, 'sdk_python_version': metadata['python'],
        'sdk_version': metadata['sdk'], 'rpc_source_sha256': rpc_identity,
        'semantic_background_writes_reviewed_by_caller': True, 'status': 'failed',
        'test_count': 0, 'junit_sha256': None, 'error': None}
    try:
        command = [sys.executable, '-B', '-X', 'utf8', '-m', 'pytest', *TESTS, '-q',
                   '--basetemp', str(output / 'pytest'), '--junitxml', str(junit)]
        code, _ = owned_run(command, cwd=root, env=env, timeout=300)
        require(code == 0, 'management_pytest_failed')
        count, junit_hash = junit_count(junit)
        receipt.update(test_count=count, junit_sha256=junit_hash)
        require(probe.source_identity(root) == before and probe.management_identity(root) == rpc_identity
            and probe.digest(sdk.read_bytes()) == sdk_hash, 'management_source_or_sdk_changed')
        receipt['status'] = 'completed'
        probe.write_new(output / 'receipt.json', receipt)
        probe.write_new(output / 'management-verification.json', {
            'sdk_version': '2.0.3', 'rpc_source_sha256': rpc_identity,
            'real_sdk_rpc_verified': True, 'semantic_background_writes_disabled': True})
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
