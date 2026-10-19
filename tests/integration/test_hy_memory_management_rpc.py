"""真实 SDK、真实 JSONL 与 Chroma；合成 transport、socket 禁网、零供应商调用。"""

from dataclasses import replace
from contextlib import contextmanager
from datetime import UTC,datetime
import json
import os
from pathlib import Path
import subprocess

import pytest

from longmemory.methods.hy_memory.process_client import HyProcessClient,clean_environment
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE,HyResponseError
from longmemory.methods.hy_memory.assembly import HyState


ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ.get('LONGMEMORY_TEST_HY_PYTHON',str(ROOT/'local/runtime/hy-memory/.venv/Scripts/python.exe')))
pytestmark=pytest.mark.skipif(not SDK.is_file(),reason='owner-installed SDK required')


@contextmanager
def owned(directory,settings):
    state=HyState(directory,settings,create=True);state.acquire()
    try:yield
    finally:state.release()


def add(client,settings):
    return client.add([{'role':'user','content':'合成用户喜欢无糖乌龙茶'}],user_id=settings.user_id,
        agent_id=settings.agent_id,source=SOURCE_NAMESPACE,scene='chat',session_id='synthetic',
        memory_at=datetime(2026,1,1,tzinfo=UTC),request_id='synthetic',
        meta={'namespace':SOURCE_NAMESPACE,'role':'user','source_event_ids':['synthetic']})


def test_real_process_management_permissions_update_delete_and_restart(tmp_path):
    settings=HySettings(user_id='synthetic-management-wire',model_mode='synthetic_transport')
    client=HyProcessClient(python=SDK,workspace=tmp_path,settings=settings,create=True)
    try:
        add(client,settings)
        row=client.list_memories(user_id=settings.user_id,agent_id=settings.agent_id)['vdb']['memories'][0]
        memory_id=row['memory_id'];caps=client.management_capabilities()
        assert not caps['update'] and not caps['delete'] and not caps['profile']
        assert client.history(memory_id=memory_id)==[]
        with pytest.raises(HyResponseError,match='state_unknown'):
            client.update(memory_id=memory_id,content='未授权的写')
        assert client.get(memory_id=memory_id)['content']==row['content']
    finally:client.close()
    enabled=replace(settings,management_writes_enabled=True)
    assert enabled.identity()==settings.identity()
    client=HyProcessClient(python=SDK,workspace=tmp_path,settings=enabled,create=False)
    try:
        assert client.management_capabilities()['update'] and client.management_capabilities()['delete']
        result=client.update(memory_id=memory_id,content='合成用户明确纠正为喜欢绿茶')
        assert result['success'] is True and result['memory_id']==memory_id
        assert client.get(memory_id=memory_id)['content']=='合成用户明确纠正为喜欢绿茶'
        assert client.history(memory_id=memory_id)==[]
        assert client.diagnostics()['management_embedding_attempts']==1
        assert client.diagnostics()['management_llm_attempts_blocked']==0
    finally:client.close()
    client=HyProcessClient(python=SDK,workspace=tmp_path,settings=enabled,create=False)
    try:
        assert client.get(memory_id=memory_id)['content']=='合成用户明确纠正为喜欢绿茶'
        assert client.delete(memory_id=memory_id)['deleted_count']==1
        assert client.get(memory_id=memory_id) is None
        assert client.diagnostics()['external_http_attempts']==0
        assert client.diagnostics()['simulated_model_requests']==0
    finally:client.close()
    client=HyProcessClient(python=SDK,workspace=tmp_path,settings=enabled,create=False)
    try:assert client.get(memory_id=memory_id) is None
    finally:client.close()


def test_profile_scope_is_created_only_for_trusted_fresh_space_and_rechecked(tmp_path):
    settings=HySettings(user_id='synthetic-profile-scope',model_mode='synthetic_transport',
        management_exclusive_profile=True)
    fresh=tmp_path/'fresh'
    with owned(fresh,settings):
        check_profile_scope(fresh,settings)
    client=HyProcessClient(python=SDK,workspace=fresh,settings=settings,create=False)
    try:assert not client.management_capabilities()['profile']  # owner 已释放。
    finally:client.close()
    old=tmp_path/'preexisting'
    client=HyProcessClient(python=SDK,workspace=old,settings=replace(settings,management_exclusive_profile=False),create=True)
    client.close()
    client=HyProcessClient(python=SDK,workspace=old,settings=settings,create=False)
    try:assert not client.management_capabilities()['profile'] and not (old/'management-scope.json').exists()
    finally:client.close()


def check_profile_scope(fresh,settings):
    client=HyProcessClient(python=SDK,workspace=fresh,settings=settings,create=True)
    try:
        assert client.management_capabilities()['exclusive_user_profile']
        assert client.get_user_profile(user_id=settings.user_id)['profile'] is None
        with pytest.raises(HyResponseError):client.get_user_profile(user_id='foreign')
        with pytest.raises(HyResponseError):
            client.add([{'role':'user','content':'foreign'}],user_id='foreign',
                agent_id=settings.agent_id,source=SOURCE_NAMESPACE,memory_at=datetime(2026,1,1,tzinfo=UTC))
    finally:client.close()
    client=HyProcessClient(python=SDK,workspace=fresh,settings=settings,create=False)
    try:assert client.management_capabilities()['profile']
    finally:client.close()
    proof=fresh/'management-scope.json';data=json.loads(proof.read_text(encoding='utf-8'))
    data['agent_id']='different';proof.write_text(json.dumps(data),encoding='utf-8')
    client=HyProcessClient(python=SDK,workspace=fresh,settings=settings,create=False)
    try:assert not client.management_capabilities()['profile']
    finally:client.close()


def test_real_sdk_full_node_audit_update_raw_preservation_and_chain_delete_effects(tmp_path):
    result=subprocess.run([str(SDK),'-I','-X','utf8','-B',str(ROOT/'tests/fixtures/hy_memory_management_audit.py'),str(tmp_path/'audit')],
        cwd=ROOT,env=clean_environment(tmp_path),capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['update']['changed_node_count']==1 and report['update']['raw_unchanged']
    assert report['isolated_delete']['changed_node_count']==1 and report['isolated_delete']['raw_unchanged']
    assert report['summary_update_single_node'] and report['profile_history_no_model_no_node_change']
    assert report['native_chain_delete']['head']['native_restored_predecessor']
    assert report['native_chain_delete']['middle']['native_changed_node_count']==3
    assert report['native_chain_delete']['tail']['native_changed_node_count']==2
    assert report['platform_evolution_overlay_and_uncertain_exclusion']
    assert report['platform_delete_refused_without_uncertain_audit']
