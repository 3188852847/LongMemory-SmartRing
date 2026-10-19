"""独立 SDK 解释器的禁网专项；仅向新合成库注入测试拓扑，不是部署入口。"""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid5,NAMESPACE_URL


ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))


def audit(directory):
    from longmemory.methods.hy_memory.worker import ProtocolService
    from longmemory.methods.hy_memory.settings import HySettings
    from longmemory.methods.hy_memory.management_rpc import HyManagementDenied
    from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE
    from longmemory.methods.hy_memory.assembly import HyState
    from hy_memory.models.memory import MemoryLayer,MemoryStatus

    settings=HySettings(user_id="synthetic-management-audit",model_mode="synthetic_transport",
        management_writes_enabled=True,management_exclusive_profile=True)
    state=HyState(directory,settings,create=True);state.acquire()
    service=ProtocolService()
    service.execute("initialize",{"workspace":str(directory),"settings":settings.wire(),"create":True})
    client=service.client
    result={"fixture_private_seed_only":True,"mutations_use_public_sdk":True}
    def snapshot():
        # 仅测试读取包括 RAW 的完整 Chroma 记录，管理协议不暴露此接口。
        data=client._vector_store._collection.get(include=["documents","metadatas","embeddings"])
        return {key:json.dumps([data['documents'][i],data['metadatas'][i],data['embeddings'][i].tolist()],
            ensure_ascii=False,sort_keys=True) for i,key in enumerate(data['ids'])}
    def changes(before,after):
        return {key for key in before.keys()|after.keys() if before.get(key)!=after.get(key)}
    def seed(node):
        client._loop_thread.run(client._vector_store.upsert(node))
    try:
        caps=service.execute("management_capabilities",{})
        assert caps['profile'] and caps['exclusive_user_profile'] and caps['update'] and caps['delete']
        added=service.execute("add",{"data":[{"role":"user","content":"合成用户喜欢无糖乌龙茶"}],
            "user_id":settings.user_id,"agent_id":settings.agent_id,"source":SOURCE_NAMESPACE,
            "scene":"chat","session_id":"fixture","memory_at":datetime(2026,1,1,tzinfo=UTC).isoformat(),
            "request_id":"synthetic-only","meta":{"namespace":SOURCE_NAMESPACE,"role":"user",
                "source_event_ids":["synthetic-only"]}})
        row=client.list_memories(user_id=settings.user_id,agent_id=settings.agent_id)['vdb']['memories'][0]
        memory_id=row['memory_id']
        template=client._loop_thread.run(client._vector_store.get_by_id(memory_id))
        before=snapshot();record=client.get(memory_id)
        assert service.execute('history',{'memory_id':memory_id})==[]
        counters=service.budget.report()
        updated=service.execute('update',{'memory_id':memory_id,'content':'合成用户明确纠正为喜欢绿茶'})
        after=snapshot();current=client.get(memory_id)
        assert changes(before,after)=={memory_id}
        assert before[added['memory_id']]==after[added['memory_id']]
        assert current['meta']==record['meta'] and current['custom']==record['custom']
        assert service.execute('history',{'memory_id':memory_id})==[]
        result['update']={'success':updated['success'],'changed_node_count':1,'raw_unchanged':True,
            'other_nodes_unchanged':True,'meta_custom_unchanged':True,'history_recording':False,
            'embedding_attempt_delta':service.budget.management_embedding_attempts-counters['management_embedding_attempts'],
            'llm_attempts_blocked':service.budget.management_llm_attempts_blocked}
        assert result['update']['embedding_attempt_delta']==1

        # Chroma 对非 UUID ID 再做 uuid5 映射；测试拓扑直接用 UUID，比较同一主键。
        summary=replace(template,node_id=str(uuid5(NAMESPACE_URL,'synthetic-summary')),layer=MemoryLayer.L3_SUMMARY,content='合成会话摘要')
        seed(summary);before=snapshot()
        service.execute('update',{'memory_id':summary.node_id,'content':'合成用户明确纠正的会话摘要'})
        assert changes(before,snapshot())=={summary.node_id}
        result['summary_update_single_node']=True

        basic=replace(template,node_id=str(uuid5(NAMESPACE_URL,'synthetic-profile')),layer=MemoryLayer.L0_BASIC_INFO,
            content='合成用户姓名',custom={**template.custom,'basic_info_kv':{'name':'合成甲'}})
        seed(basic);before=snapshot();counters=service.budget.report()
        profile=service.execute('get_user_profile',{'user_id':settings.user_id})
        assert profile['profile']['basic_info']=={'name':'合成甲'}
        assert service.execute('history',{'memory_id':memory_id})==[]
        assert snapshot()==before
        assert service.budget.report()['simulated_model_requests']==counters['simulated_model_requests']
        result['profile_history_no_model_no_node_change']=True

        before=snapshot();counters=service.budget.report()
        deleted=service.execute('delete',{'memory_id':memory_id})
        assert deleted['success'] is True and deleted['deleted_count']==1
        assert changes(before,snapshot())=={memory_id} and client.get(memory_id) is None
        assert snapshot()[added['memory_id']]==before[added['memory_id']]
        assert service.budget.report()['simulated_model_requests']==counters['simulated_model_requests']
        result['isolated_delete']={'changed_node_count':1,'raw_unchanged':True,'model_attempt_delta':0}

        result['native_chain_delete']={}
        for target in ('head','middle','tail'):
            ids={name:str(uuid5(NAMESPACE_URL,f'synthetic-{target}-{name}')) for name in ('head','middle','tail')}
            nodes={
                'head':replace(template,node_id=ids['head'],content='新事实',supersedes=[ids['middle']],superseded_by=[]),
                'middle':replace(template,node_id=ids['middle'],content='中间事实',supersedes=[ids['tail']],
                    superseded_by=[ids['head']],is_latest=False,status=MemoryStatus.SUPERSEDED),
                'tail':replace(template,node_id=ids['tail'],content='最早事实',supersedes=[],
                    superseded_by=[ids['middle']],is_latest=False,status=MemoryStatus.SUPERSEDED),
            }
            for node in nodes.values():seed(node)
            before=snapshot()
            for name in ids:
                try:service.execute('delete',{'memory_id':ids[name]})
                except HyManagementDenied:pass
                else:raise AssertionError('chain deletion must be rejected before SDK')
            assert snapshot()==before
            if target == 'head':
                # 保留真实SDK生成的演化链返回结构，经平台method/admin再投影。
                from longmemory.methods.hy_memory.method import HyMemoryMethod
                from longmemory.methods.hy_memory.administration import HyAdministration, HyManagementConflict
                from longmemory.methods.contracts import MemoryEvent
                class LocalClient:
                    def __init__(self): self.state = state
                    def __getattr__(self, name):
                        def rpc(*args, **kwargs):
                            if args: kwargs['query'] = args[0]
                            return service.execute(name, kwargs)
                        return rpc
                    def close(self): pass
                method = HyMemoryMethod(settings=settings, client_factory=LocalClient)
                admin = HyAdministration(method, serialized_writes=True)
                with admin._ledger() as db:
                    db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,NULL)',
                        ('historical-audit','synthetic-hash','correct',ids['middle'],
                         'historical-correction-source','a'*64,'completed','2026-10-19T00:00:00+00:00'))
                recalled = method.recall('中间事实')
                assert any(row.item_id == ids['head'] and 'historical-correction-source' in row.source_event_ids for row in recalled.retrieved)
                revision = admin.get_item(ids['head']).revision
                request = str(uuid5(NAMESPACE_URL,'delete-head-refused'))
                try:
                    admin.extension('delete', item_id=ids['head'], request_id=request,
                        expected_revision=revision, source=MemoryEvent('hy-management:'+request,'user',
                            '删除这条记忆：'+ids['head'],datetime.now(UTC)))
                except HyManagementConflict: pass
                else: raise AssertionError('platform must refuse chain deletion before running audit')
                assert admin.extension('operations')['total'] == 1
                with admin._ledger() as db:
                    db.execute("UPDATE operations SET state='uncertain'")
                recalled = method.recall('中间事实')
                assert all(row.item_id != ids['head'] for row in recalled.retrieved)
                assert '中间事实' not in recalled.context
                assert recalled.warning_code == 'hy_management_uncertain_items_excluded'
                result['platform_evolution_overlay_and_uncertain_exclusion'] = True
                result['platform_delete_refused_without_uncertain_audit'] = True
                method.close()
            # 只在本合成库直接实测原生公开 delete；不把它开放为 worker 的链操作。
            native=client.delete(ids[target]);after=snapshot()
            assert native['success'] is True
            expected={ids['head'],ids['middle']} if target=='head' else set(ids.values()) if target=='middle' else {ids['middle'],ids['tail']}
            assert changes(before,after)==expected
            restored=client.get(ids['middle']) if target=='head' else None
            if restored:assert restored['status']=='active' and restored['is_latest'] is True
            result['native_chain_delete'][target]={'worker_refused_all_members_unchanged':True,
                'native_changed_node_count':len(expected),'native_restored_predecessor':bool(restored)}
        result['capabilities']=caps
        result['diagnostics']=service.budget.report()
        result['sdk_client_sha256']=hashlib.sha256(Path(sys.prefix,'Lib/site-packages/hy_memory/client.py').read_bytes()).hexdigest()
    finally:
        service.execute('close',{})
        state.release()
    result['history_db_exists']=(directory/'sdk/history.db').exists()
    assert result['diagnostics']['external_http_attempts']==0
    assert result['diagnostics']['management_llm_attempts_blocked']==0
    assert result['history_db_exists'] is False
    return result


if __name__=='__main__':
    with open(os.devnull,'w',encoding='utf-8') as sink:
        with redirect_stdout(sink),redirect_stderr(sink):
            result=audit(Path(sys.argv[1]).resolve())
    print(json.dumps(result,ensure_ascii=False))
