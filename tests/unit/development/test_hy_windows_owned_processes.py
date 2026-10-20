"""真实Windows管道与Job测试：仅标准库合成进程，SDK仅查询版本元数据。"""

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
import hy_management_receipt as receipt

probe = receipt.probe
SDK = ROOT / 'local/runtime/hy-memory/.venv/Scripts/python.exe'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='real Windows Job and handle checks')

# 后代不继承输出管道，确保成功路径确实由Job清除仍存活的两级后代。
NODE = '''import hashlib,json,os,subprocess,sys,time
from pathlib import Path
if sys.argv[1]=='--worker':
    data=sys.stdin.buffer.read()
    config=json.loads(data)
    root=Path(config['arm_directory'])
    label='target'
    mode=config['test_mode']
    (root/'input.json').write_text(json.dumps({'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}))
else:
    root=Path(sys.argv[2])
    label=sys.argv[1]
    mode='descendant'
(root/(label+'.pid')).write_text(str(os.getpid()))
if label!='grandchild':
    child='child' if label=='target' else 'grandchild'
    subprocess.Popen([sys.executable,'-I','-B',__file__,child,str(root)],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
if label=='target':
    deadline=time.monotonic()+15
    while not (root/'release').is_file():
        if time.monotonic()>deadline: sys.exit(93)
        time.sleep(.01)
    if mode in ('timeout','cancelled'): time.sleep(60)
    print(json.dumps({'status':'completed',**json.loads((root/'input.json').read_text())}),flush=True)
    sys.exit(7 if mode=='nonzero' else 0)
time.sleep(60)
'''


def windows_handles():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetExitCodeProcess.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


@pytest.mark.parametrize('runner', ['management', 'campus'])
@pytest.mark.parametrize('mode', ['success', 'nonzero', 'timeout', 'cancelled'])
def test_real_windows_output_config_exit_and_owned_descendants(tmp_path, monkeypatch, runner, mode):
    worker = tmp_path / 'synthetic_worker.py'
    worker.write_text(NODE, encoding='utf-8')
    configuration = {'arm_directory': str(tmp_path), 'test_mode': mode,
        'first': '完整配置起点', 'padding': '字节\n\\"' * 12000, 'last': '完整配置末尾'}
    # 与campus.child_process相同的JSON编码；管理门在许可字节后显式转发此完整配置。
    payload = json.dumps(configuration).encode()
    expected = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    assert len(payload) > 65536
    api, handles, observed, failures = windows_handles(), {}, {}, []
    ready, finished = Event(), Event()

    def observe():
        try:
            deadline = monotonic() + 10
            while len(handles) < 3 and monotonic() < deadline and not finished.is_set():
                for label in ('target', 'child', 'grandchild'):
                    path = tmp_path / (label + '.pid')
                    if label not in handles and path.is_file():
                        text = path.read_text()
                        if not text: continue
                        pid = int(text)
                        handle = api.OpenProcess(0x100000 | 0x1000, False, pid)
                        if not handle: raise ctypes.WinError(ctypes.get_last_error())
                        handles[label] = handle
                        observed[label] = pid
                sleep(.01)
            if len(handles) != 3: raise AssertionError('owned process tree did not become ready')
            # 持有稳定进程句柄后才放行退出；不凭可能复用的PID猜测是否回收。
            (tmp_path / 'release').write_bytes(b'1')
        except BaseException as error:
            failures.append(type(error).__name__)
        finally:
            ready.set()

    real_popen, roots = subprocess.Popen, []

    def tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        roots.append(process)
        if mode == 'cancelled':
            communicate = process.communicate
            def interrupt(input, timeout):
                try:
                    communicate(input, timeout=.8)
                except subprocess.TimeoutExpired:
                    assert ready.wait(10) and not failures
                    # 注入Python取消异常；进程/管道/Job与三层进程均为真实Windows对象。
                    raise KeyboardInterrupt()
                raise AssertionError('synthetic target unexpectedly exited before cancellation')
            monkeypatch.setattr(process, 'communicate', interrupt)
        return process

    monkeypatch.setattr(subprocess, 'Popen', tracked_popen)
    monkeypatch.setattr(probe, 'TOOL', worker)
    observer = Thread(target=observe, daemon=True)
    observer.start()
    result, exception = None, None
    try:
        try:
            if runner == 'management':
                result = receipt.owned_run([sys.executable, '-I', '-B', '-X', 'utf8', worker, '--worker'],
                    cwd=tmp_path, env=receipt.clean_environment(), timeout=2 if mode == 'timeout' else 15,
                    capture=True, input_bytes=payload)
            else:
                result = probe.child_process(configuration, timeout=2 if mode == 'timeout' else 15)
        except BaseException as error:
            exception = error
        finally:
            finished.set()
            observer.join(10)
        assert not observer.is_alive() and not failures and ready.is_set()
        assert json.loads((tmp_path / 'input.json').read_text()) == expected
        assert len(roots) == 1 and roots[0].poll() is not None
        exit_codes = {}
        for label, handle in handles.items():
            assert api.WaitForSingleObject(handle, 2000) == 0, label + ' still running'
            value = wintypes.DWORD()
            assert api.GetExitCodeProcess(handle, ctypes.byref(value))
            exit_codes[label] = value.value
        assert exit_codes['child'] == exit_codes['grandchild'] == 1
        if mode in {'success', 'nonzero'}:
            expected_exit = 7 if mode == 'nonzero' else 0
            assert roots[0].returncode == exit_codes['target'] == expected_exit
            if runner == 'management':
                assert exception is None and result[0] == expected_exit
                assert json.loads(result[1]) == {'status': 'completed', **expected}
                stdout_bytes = len(result[1])
            elif mode == 'success':
                assert exception is None and result == {'status': 'completed', **expected}
                stdout_bytes = None  # 已由child_process解析完整stdout。
            else:
                assert isinstance(exception, probe.ProbeFailure) and str(exception) == 'probe_arm_failed'
                stdout_bytes = None
        elif mode == 'timeout':
            assert isinstance(exception, receipt.ReceiptFailure if runner == 'management' else subprocess.TimeoutExpired)
            if runner == 'management': assert str(exception) == 'management_runner_timeout'
            stdout_bytes = None
        else:
            assert isinstance(exception, KeyboardInterrupt)
            stdout_bytes = None
        (tmp_path / 'windows-evidence.json').write_text(json.dumps({'platform': sys.platform,
            'runner': runner, 'mode': mode, 'input': expected, 'process_ids': observed,
            'exit_codes': exit_codes, 'wrapper_exit_code': roots[0].returncode,
            'stdout_bytes': stdout_bytes, 'all_owned_process_handles_signaled': True,
            'exception': type(exception).__name__ if exception is not None else None}, indent=2), encoding='utf-8')
    finally:
        for handle in handles.values(): api.CloseHandle(handle)


def test_real_windows_bad_permit_starts_no_target(tmp_path):
    marker = tmp_path / 'must-not-exist'
    target = [sys.executable, '-I', '-B', '-c', 'from pathlib import Path;Path(__import__("sys").argv[1]).touch()', str(marker)]
    job = receipt.new_job()
    process = None
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', '-c', receipt.BOOTSTRAP, *target],
            cwd=tmp_path, env=receipt.clean_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(process)
        output, _ = process.communicate(b'0' + b'{"tail":"must not be executed"}', timeout=10)
        assert process.returncode == 97 and output == b'' and not marker.exists()
    finally:
        job.close()
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()


@pytest.mark.skipif(not SDK.is_file(), reason='existing owner-installed SDK metadata only; no installation')
def test_real_windows_sdk_metadata_stdout_and_exit_code(tmp_path):
    command = [SDK, '-I', '-B', '-X', 'utf8', '-c', receipt.METADATA]
    direct = subprocess.run(command, cwd=tmp_path, env=receipt.clean_environment(), capture_output=True, timeout=20)
    code, data = receipt.owned_run(command, cwd=tmp_path, env=receipt.clean_environment(), timeout=20, capture=True)
    assert code == direct.returncode == 0
    assert len(data) == len(direct.stdout) > 0
    assert json.loads(data) == json.loads(direct.stdout) == {'python': '3.12.13', 'sdk': '2.0.3'}
    (tmp_path / 'metadata-evidence.json').write_text(json.dumps({'platform': sys.platform,
        'returncode': code, 'stdout_bytes': len(data), 'direct_stdout_bytes': len(direct.stdout),
        'metadata': json.loads(data)}, indent=2), encoding='utf-8')
