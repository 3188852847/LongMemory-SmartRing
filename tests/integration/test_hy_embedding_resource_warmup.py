"""实际SDK公开资源预备，不建客户端/请求，不写SDK数据文件；只用合成回环。"""

import json
import os
from pathlib import Path
import subprocess

import pytest
from longmemory.methods.hy_memory.process_client import clean_environment

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get('LONGMEMORY_TEST_HY_PYTHON','missing-explicit-sdk'))


@pytest.mark.skipif(not SDK.is_file(),reason='explicit owner-installed SDK required')
@pytest.mark.parametrize('mode',['baseline','prepared'])
def test_fixed_sdk_resource_preparation_is_read_only_and_embed_behavior_is_preserved(tmp_path,mode):
    fixture=ROOT/'tests/fixtures/hy_embedding_resource_probe.py'
    script='import sys,runpy;sys.path.insert(0,'+repr(str(ROOT/'src'))+');sys.argv=['+repr(str(fixture))+','+repr(mode)+'];runpy.run_path('+repr(str(fixture))+',run_name="__main__")'
    result=subprocess.run([str(SDK),'-I','-X','utf8','-B','-c',script],cwd=tmp_path,
        env=clean_environment(tmp_path),capture_output=True,text=True,encoding='utf-8',timeout=35)
    assert result.returncode==0,result.stderr[-2000:]
    receipt=json.loads(result.stdout.splitlines()[-1]);preparation=receipt['preparation']
    assert not preparation['resources_loaded_before']
    assert preparation['resources_loaded_after']==(mode=='prepared')
    assert preparation['files_unchanged'] and preparation['result']['prepared']
    assert preparation['http_requests']=={'embedding':0,'other':0}
    assert preparation['client_cache_entries']==preparation['vector_cache_entries']==0
    assert receipt['counts']=={'embedding':2,'other':0} and receipt['external_http_attempts']==0
    assert receipt['local_gateway_requests']==2
    for sample in receipt['samples']:
        assert 'embed_rpc_ms' not in sample['base']['stages']
        assert set(sample['detail']['stages'])=={'embed_client_get_ms','embed_http_headers_ms'}
