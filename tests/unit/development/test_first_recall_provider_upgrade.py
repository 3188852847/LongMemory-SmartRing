"""实际安装器的精确升级许可；只操作合成目标，不访问共享provider。"""

import hashlib
import importlib.util
import os
from pathlib import Path

import pytest


ROOT=Path(__file__).resolve().parents[3]
OLD='7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9'


def test_approved_7241_upgrade_exact_bytes_idempotent_and_unknown_rejected(tmp_path,monkeypatch):
    script=ROOT/'scripts/development/xiaozhi/setup.py'
    monkeypatch.syspath_prepend(str(script.parent))
    spec=importlib.util.spec_from_file_location('synthetic_v2_setup',script)
    setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    old=(ROOT/'tests/fixtures/xiaozhi_provider_c74.py.txt').read_bytes()
    assert hashlib.sha256(old).hexdigest()==OLD
    assert OLD in setup.LEGACY_MEMORY_PROVIDER_SHA256
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
    # 换行转换和旧版追加注释都不是获批原字节；不得扩成相似内容匹配。
    for unknown in (b'# synthetic owner modification\n',old+b'# owner edit\n',
                    old.replace(b'\n',b'\r\n')):
        target.write_bytes(unknown)
        with pytest.raises(setup.SetupError):setup.install_memory_provider(tmp_path,allow_known_update=True)
        assert target.read_bytes()==unknown and base.read_bytes()==b'synthetic untouched base'
