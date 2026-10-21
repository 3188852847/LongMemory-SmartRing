"""实际安装器的合成副本接力；不修改生产白名单或共享provider。"""

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest


ROOT=Path(__file__).resolve().parents[3]
OLD='7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9'


def test_approved_7241_upgrade_exact_bytes_idempotent_and_unknown_rejected(tmp_path,monkeypatch):
    script=ROOT/'scripts/development/xiaozhi/setup.py'
    monkeypatch.syspath_prepend(str(script.parent))
    spec=importlib.util.spec_from_file_location('synthetic_v2_setup',script)
    setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    result=subprocess.run(['git','show','c74b88834683080d4dc4ee4b770f48707ff5b349:scripts/development/xiaozhi/longmemory_provider.py'],
        cwd=ROOT,capture_output=True)
    if result.returncode:pytest.skip('immutable baseline unavailable; no fetch')
    old=result.stdout
    assert hashlib.sha256(old).hexdigest()==OLD
    original_allowlist=set(setup.LEGACY_MEMORY_PROVIDER_SHA256)
    # 临时模块内存集合只模拟AI后续审查的升级许可，绝不修改setup.py。
    monkeypatch.setattr(setup,'LEGACY_MEMORY_PROVIDER_SHA256',original_allowlist|{OLD})
    base=tmp_path/'core/providers/memory/base.py';base.parent.mkdir(parents=True)
    base.write_bytes(b'synthetic untouched base')
    target=base.parent/'longmemory/longmemory.py';target.parent.mkdir();target.write_bytes(old)
    with pytest.raises(setup.SetupError):setup.install_memory_provider(tmp_path)
    assert target.read_bytes()==old
    assert setup.install_memory_provider(tmp_path,allow_known_update=True)==target
    final=(script.parent/'longmemory_provider.py').read_bytes()
    assert target.read_bytes()==final and final!=old
    os.utime(target,ns=(1700000000000000000,1700000000000000000))
    assert setup.install_memory_provider(tmp_path,allow_known_update=True)==target
    assert target.stat().st_mtime_ns==1700000000000000000
    unknown=b'# synthetic owner modification\n';target.write_bytes(unknown)
    with pytest.raises(setup.SetupError):setup.install_memory_provider(tmp_path,allow_known_update=True)
    assert target.read_bytes()==unknown and base.read_bytes()==b'synthetic untouched base'
