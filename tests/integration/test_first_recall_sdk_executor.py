"""固定SDK真实执行器的正常、异常及排队/运行取消；无模型或HTTP。"""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get('LONGMEMORY_TEST_HY_PYTHON',str(ROOT/'local/runtime/hy-memory/.venv/Scripts/python.exe')))


@pytest.mark.skipif(not SDK.is_file(),reason='isolated SDK missing')
def test_fixed_sdk_original_vdb_executor_preserves_results_errors_and_cancel(tmp_path):
    fixture=ROOT/'tests/fixtures/ab_first_recall_sdk_executor.py'
    script='import sys,runpy;sys.path.insert(0,'+repr(str(ROOT/'src'))+');runpy.run_path('+repr(str(fixture))+',run_name="__main__")'
    result=subprocess.run([str(SDK),'-I','-X','utf8','-B','-c',script],cwd=tmp_path,
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr[-2000:]
    receipt=json.loads(result.stdout.splitlines()[-1])
    assert [case['case'] for case in receipt['cases']]==['success','error','queued','started']
    assert all(case['calls']==1 and case['executor_preserved'] and not case['late_mutation'] for case in receipt['cases'])
    assert receipt['cases'][2]['detail'] is None
