"""待ROOT/AI审查的纯合成协议模型；不接入任何运行时、HTTP服务或安装器。"""

import json
import math
import re


BASELINE = 'c74b88834683080d4dc4ee4b770f48707ff5b349'
BASE_STAGES = frozenset(('api_queue_ms','api_prepare_ms','runtime_outer_lock_ms','runtime_entry_ms',
    'sdk_rpc_lock_ms','sdk_roundtrip_ms','sdk_execute_ms','sdk_search_ms','sdk_profile_ms','sdk_add_ms',
    'source_enrich_ms','reader_get_ms','tokenize_ms','embedding_truncate_ms','embed_rpc_ms',
    'vdb_query_ms','vdb_get_ms','vdb_list_ms','archive_ms','hy_observe_ms','hy_recall_ms',
    'management_overlay_ms','prepare_lock_wait_ms','prepare_command_ms','prepare_observe_ms',
    'prepare_recall_ms','prepare_scenario_ms','prepare_persona_ms','prepare_total_ms'))
DETAIL_STAGES = frozenset(('embed_client_get_ms','embed_http_headers_ms','embed_gateway_ms',
    'embed_gateway_lock_wait_ms','embed_bge_encode_ms','vdb_query_pool_wait_ms','vdb_query_backend_ms'))
CURRENT_OWNED_PROVIDER = '7241a12e6fe9d8c250245cf781167555c7df53375ef643bc02ebcaf1a18240e9'


def valid(value, trace, version, stages):
    if (not isinstance(value,dict) or set(value)!={'version','trace_id','stages'}
            or type(value['version']) is not int or value['version']!=version or value['trace_id']!=trace
            or not isinstance(trace,str) or re.fullmatch(r'[0-9a-f]{24,32}',trace) is None
            or not isinstance(value['stages'],dict) or set(value['stages'])-stages):
        return False
    return all(isinstance(item,dict) and set(item)=={'calls','total_ms'}
        and type(item['calls']) is int and 1<=item['calls']<=100000
        and type(item['total_ms']) in (int,float) and 0<=item['total_ms']<=3600000
        and math.isfinite(item['total_ms']) for item in value['stages'].values())


def encode(value):
    text=json.dumps(value,separators=(',',':'),sort_keys=True)
    if len(text)>4096:
        raise ValueError('synthetic_contract_header_large')
    return text


def response_fixture(request_headers, *, base, detail=None, new_server=False, status=200, body=None):
    """只生成旁路header；status/body按对象原样返回，绝不改变业务决策。"""
    headers={}
    if request_headers.get('X-Memory-Observe')=='1':
        assert valid(base,base['trace_id'],1,BASE_STAGES)
        headers['X-Memory-Observation']=encode(base)
        if new_server and request_headers.get('X-Memory-Observe-Detail')=='2' and detail is not None:
            assert valid(detail,base['trace_id'],2,DETAIL_STAGES)
            headers['X-Memory-Observation-Detail']=encode(detail)
    return status,body,headers


def receive_fixture(headers, *, trace, new_client=False):
    """v1基础记录形状不变；新版另产出v2旁路记录，缺失不填0。"""
    def read(name,version,stages):
        raw=headers.get(name)
        if not isinstance(raw,str) or len(raw)>4096:
            return None
        try:
            value=json.loads(raw)
            return value if valid(value,trace,version,stages) else None
        except (ValueError,TypeError,RecursionError):
            return None
    base=read('X-Memory-Observation',1,BASE_STAGES)
    if not new_client:
        return base,None
    detail=read('X-Memory-Observation-Detail',2,DETAIL_STAGES)
    state=('received' if detail is not None else 'unavailable'
           if 'X-Memory-Observation-Detail' not in headers else 'invalid')
    return base,{'version':2,'round_id':trace,'state':state,'observation':detail}


async def roundtrip_fixture(operation,request_headers,**metadata):
    """合成调用只执行一次；异常/取消原样传播，不制造业务响应或重试。"""
    status,body=await operation()
    return response_fixture(request_headers,status=status,body=body,**metadata)


def deployment_guard_fixture(current_hash, *, approved_old, final_hash):
    """仅合成升级判定；不读取/写入已安装provider，不新增已批准版本。"""
    if current_hash==final_hash:
        return 'already_current'
    return 'upgrade_after_review' if current_hash in approved_old else 'reject_unknown'


def examples():
    trace='a'*32
    base={'version':1,'trace_id':trace,'stages':{
        'api_prepare_ms':{'calls':1,'total_ms':30.0},
        'prepare_recall_ms':{'calls':1,'total_ms':26.0},
        'sdk_roundtrip_ms':{'calls':1,'total_ms':24.0},
        'sdk_execute_ms':{'calls':1,'total_ms':22.0},
        'sdk_search_ms':{'calls':1,'total_ms':20.0},
        'embed_rpc_ms':{'calls':1,'total_ms':9.25},
        'vdb_query_ms':{'calls':1,'total_ms':6.0}}}
    detail={'version':2,'trace_id':trace,'stages':{name:{'calls':1,'total_ms':value} for name,value in (
        ('embed_client_get_ms',1.25),('embed_http_headers_ms',7.0),('embed_gateway_ms',6.0),
        ('embed_gateway_lock_wait_ms',2.0),('embed_bge_encode_ms',3.0),
        ('vdb_query_pool_wait_ms',.25),('vdb_query_backend_ms',4.5))}}
    output={'kind':'synthetic_contract_example_not_measurement','baseline_commit':BASELINE,'cases':[]}
    for name,new_client,new_server in (('old_client_new_server',False,True),
            ('new_client_old_server',True,False),('new_client_new_server',True,True)):
        request={'X-Memory-Observe':'1'}
        if new_client:
            request['X-Memory-Observe-Detail']='2'
        status,body,headers=response_fixture(request,base=base,detail=detail,new_server=new_server,
            body={'unchanged_business_result':True})
        parsed,sidecar=receive_fixture(headers,trace=trace,new_client=new_client)
        output['cases'].append({'case':name,'request_headers':request,'response_headers':headers,
            'business_status':status,'business_body':body,'base_observation':parsed,'detail_record':sidecar})
    return output
