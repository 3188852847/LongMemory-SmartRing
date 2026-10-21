"""只验证协商设计；不依赖未提交的运行时草稿，不启动服务/SDK/模型。"""

from copy import deepcopy
import asyncio
import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest


ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('ab_first_recall_contract',ROOT/'tests/fixtures/ab_first_recall_observation_contract.py')
contract=importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_three_way_matrix_keeps_v1_byte_for_byte_and_details_explicit():
    cases={row['case']:row for row in contract.examples()['cases']}
    base_headers=[row['response_headers']['X-Memory-Observation'] for row in cases.values()]
    assert len(set(base_headers))==1
    assert all(row['base_observation'] is not None for row in cases.values())
    assert cases['old_client_new_server']['detail_record'] is None
    assert 'X-Memory-Observation-Detail' not in cases['old_client_new_server']['response_headers']
    unavailable=cases['new_client_old_server']['detail_record']
    assert unavailable['state']=='unavailable' and unavailable['observation'] is None
    assert cases['new_client_new_server']['detail_record']['state']=='received'
    assert set(cases['new_client_new_server']['detail_record']['observation']['stages'])==contract.DETAIL_STAGES


def test_existing_c74_v1_parser_rejects_new_stage_and_accepts_all_base_examples():
    # 固定c74公开源码及摘要；浅克隆也必须执行旧版解析兼容检查。
    source=(ROOT/'tests/fixtures/hy_observation_c74.py.txt').read_bytes()
    assert hashlib.sha256(source).hexdigest()=='7129844923491ef62e6eadb11a02cbeaaf5969ed48bd0fbfd816dac9bacf90da'
    namespace={}
    exec(compile(source,'<c74-v1-observation>','exec'),namespace)
    assert namespace['STAGES']==contract.BASE_STAGES
    for row in contract.examples()['cases']:
        base=row['base_observation']
        assert namespace['valid_snapshot'](base,base['trace_id'])
    invalid=deepcopy(contract.examples()['cases'][0]['base_observation'])
    invalid['stages']['embed_client_get_ms']={'calls':1,'total_ms':1.0}
    assert not namespace['valid_snapshot'](invalid,invalid['trace_id'])
    source=(ROOT/'tests/fixtures/xiaozhi_provider_c74.py.txt').read_bytes()
    assert hashlib.sha256(source).hexdigest()=='7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9'
    tree=ast.parse(source)
    stages=next(item for item in tree.body if isinstance(item,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='_OBSERVATION_STAGES' for target in item.targets))
    function=next(item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name=='_observation_header')
    old_voice={'json':json,'math':math,'_OBSERVATION_STAGES':frozenset(ast.literal_eval(stages.value.args[0]))}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<c74-voice-v1-parser>','exec'),old_voice)
    assert old_voice['_OBSERVATION_STAGES']==contract.BASE_STAGES
    for row in contract.examples()['cases']:
        assert old_voice['_observation_header'](row['response_headers']['X-Memory-Observation'],'a'*32)==row['base_observation']
    assert old_voice['_observation_header'](json.dumps(invalid),'a'*32) is None


@pytest.mark.parametrize('status',[200,400,409,503])
def test_negotiation_never_changes_business_status_or_body(status):
    case=contract.examples()['cases'][-1]
    detail=case['detail_record']['observation']
    body={'private_body':'not-observation','original_status':status}
    for requested in ({},{'X-Memory-Observe':'1'},case['request_headers']):
        actual_status,actual_body,headers=contract.response_fixture(requested,
            base=case['base_observation'],detail=detail,new_server=True,status=status,body=body)
        assert actual_status==status and actual_body is body
        assert 'private_body' not in repr(headers) and 'not-observation' not in repr(headers)


@pytest.mark.parametrize('requested',[{}, {'X-Memory-Observe-Detail':'2'},
    {'X-Memory-Observe':'1','X-Memory-Observe-Detail':'1'},
    {'X-Memory-Observe':'1','X-Memory-Observe-Detail':'3'}])
def test_details_are_not_default_and_unsupported_versions_do_not_change_base(requested):
    case=contract.examples()['cases'][-1]
    _,_,headers=contract.response_fixture(requested,base=case['base_observation'],
        detail=case['detail_record']['observation'],new_server=True)
    assert 'X-Memory-Observation-Detail' not in headers
    assert ('X-Memory-Observation' in headers)==(requested.get('X-Memory-Observe')=='1')


@pytest.mark.parametrize('mutation',['version','trace','stage','extra_root','extra_item','non_numeric','nan','huge','header_large'])
def test_bad_detail_preserves_good_base_and_does_not_echo_private_payload(mutation):
    case=contract.examples()['cases'][-1]
    headers=dict(case['response_headers'])
    detail=deepcopy(case['detail_record']['observation'])
    first=next(iter(detail['stages'].values()))
    if mutation=='version':detail['version']=1
    elif mutation=='trace':detail['trace_id']='b'*32
    elif mutation=='stage':detail['stages']['private-question']={'calls':1,'total_ms':1}
    elif mutation=='extra_root':detail['private-path']='secret'
    elif mutation=='extra_item':first['token']='secret'
    elif mutation=='non_numeric':first['total_ms']='secret'
    elif mutation=='nan':first['total_ms']=float('nan')
    elif mutation=='huge':first['total_ms']=10**400
    headers['X-Memory-Observation-Detail']=('secret'*1000 if mutation=='header_large' else json.dumps(detail))
    base,record=contract.receive_fixture(headers,trace='a'*32,new_client=True)
    assert base==case['base_observation'] and record['state']=='invalid' and record['observation'] is None
    assert not any(word in repr(record) for word in ('secret','private-question','private-path'))


def test_partial_execution_does_not_fill_missing_stage_with_zero():
    case=contract.examples()['cases'][-1]
    detail=deepcopy(case['detail_record']['observation'])
    detail['stages']={'embed_client_get_ms':detail['stages']['embed_client_get_ms']}
    _,_,headers=contract.response_fixture(case['request_headers'],base=case['base_observation'],detail=detail,new_server=True)
    _,record=contract.receive_fixture(headers,trace='a'*32,new_client=True)
    assert record['state']=='received' and set(record['observation']['stages'])=={'embed_client_get_ms'}


def test_no_sdk_capability_no_invented_empty_detail_receipt():
    case=contract.examples()['cases'][-1]
    _,_,headers=contract.response_fixture(case['request_headers'],base=case['base_observation'],detail=None,new_server=True)
    base,record=contract.receive_fixture(headers,trace='a'*32,new_client=True)
    assert base==case['base_observation'] and record['state']=='unavailable' and record['observation'] is None


@pytest.mark.parametrize('outcome',['normal','error','cancel'])
def test_contract_roundtrip_preserves_one_call_result_exception_and_cancellation(outcome):
    case=contract.examples()['cases'][-1]
    calls=[]
    original=RuntimeError('synthetic-private-error') if outcome=='error' else asyncio.CancelledError('synthetic-private-cancel')
    body=object()
    async def business():
        calls.append(True)
        if outcome!='normal':raise original
        return 200,body
    async def run():
        call=contract.roundtrip_fixture(business,case['request_headers'],base=case['base_observation'],
            detail=case['detail_record']['observation'],new_server=True)
        if outcome=='normal':
            result=await call
            assert result[0]==200 and result[1] is body
        else:
            with pytest.raises(type(original)) as caught:await call
            assert caught.value is original
    asyncio.run(run())
    assert calls==[True]


def test_provider_upgrade_guard_is_known_only_idempotent_and_rejects_unknown():
    known=contract.CURRENT_OWNED_PROVIDER
    final='f'*64  # 仅合成目标，不是任何已批准provider源码。
    approved={known}
    assert contract.deployment_guard_fixture(known,approved_old=approved,final_hash=final)=='upgrade_after_review'
    assert contract.deployment_guard_fixture(final,approved_old=approved,final_hash=final)=='already_current'
    assert contract.deployment_guard_fixture('9'*64,approved_old=approved,final_hash=final)=='reject_unknown'


def test_frozen_examples_are_exact_reference_fixture_output():
    path=ROOT/'docs/development/parallel/AB-first-recall-observation-examples-20261021.json'
    assert json.loads(path.read_text(encoding='utf-8'))==contract.examples()
