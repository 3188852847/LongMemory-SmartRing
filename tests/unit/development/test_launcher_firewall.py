"""防火墙测试不执行 UAC，不改变任何真实规则。"""
import base64
import importlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def firewall(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts/development/launcher'))
    return importlib.import_module('firewall')


@pytest.mark.parametrize('address,remote', [('0.0.0.0', '192.168.1.1'),
    ('192.168.1.2', '0.0.0.0/0'), ('192.168.1.2', '192.168.0.0/16'),
    ('192.168.1.2', '8.8.8.8'), ('192.168.1.2', "1.2.3.4'; exit")])
def test_scope_rejects_unsafe_values(firewall, address, remote):
    with pytest.raises(ValueError):
        firewall.scope(address, remote)


def test_allow_uses_uac_and_fixed_script(firewall, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(firewall, 'run_ps', lambda source: calls.append(source) or SimpleNamespace(returncode=0))
    firewall.change('Allow', '192.168.1.2', '192.168.1.3', tmp_path)
    source = calls[0]
    assert '-Verb RunAs' in source and '-WindowStyle Hidden' in source
    payload = source.split("'-EncodedCommand','")[1].split("'")[0]
    child = base64.b64decode(payload).decode('utf-16-le')
    assert 'firewall.ps1' in child and '-Action Allow' in child
    assert '192.168.1.3/32' in child and 'Encoding]::UTF8' in child
    assert 'ExecutionPolicy' not in source


@pytest.mark.parametrize('code', [1, 1223])
def test_failure_and_cancel_not_success(firewall, monkeypatch, tmp_path, code):
    monkeypatch.setattr(firewall, 'run_ps', lambda _: SimpleNamespace(returncode=code))
    with pytest.raises(ValueError):
        firewall.change('Revoke', '', '', tmp_path)


def test_inspection_failure_is_not_absent(firewall, monkeypatch):
    monkeypatch.setattr(firewall, 'run_ps', lambda _: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match='不是'):
        firewall.inspect('192.168.1.2')


def test_inspection_is_readonly(firewall, monkeypatch):
    calls = []
    monkeypatch.setattr(firewall, 'run_ps', lambda s: calls.append(s) or SimpleNamespace(
        returncode=0, stdout=b'{"ports":[],"rules":[]}'))
    assert firewall.inspect('192.168.1.2')['rules'] == []
    assert 'RunAs' not in calls[0]
    assert 'New-NetFirewallRule' not in calls[0]


def test_panel_constructs_without_queries(firewall, monkeypatch, tmp_path):
    # Windows Tcl 会把首次 Tk 初始化的库路径缓存到进程全局；另一个 UI 测试
    # 已销毁 root 后再次创建可能把中文路径乱码化。真实面板本来也在独立进程
    # 中打开，因此用全新解释器验证构造更贴近日常入口，且不触发任何查询。
    directory = Path(__file__).resolve().parents[3] / 'scripts/development/launcher'
    code = (
        "import sys,tkinter as tk;"
        f"sys.path.insert(0,{str(directory)!r});"
        "from firewall_panel import open_panel;"
        "root=tk.Tk();root.withdraw();"
        f"window=open_panel(root,'192.168.1.2',{str(tmp_path)!r});"
        "root.update_idletasks();root.destroy()"
    )
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=directory, env=os.environ.copy(),
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, 'firewall panel subprocess failed'
