"""一次请求的固定数值观测；跨进程只传匿名关联，不传业务正文。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import math
import re
from time import perf_counter


CURRENT = ContextVar('hy_request_observation', default=None)
LEGACY_STAGES = frozenset(('api_queue_ms','api_prepare_ms','runtime_outer_lock_ms','runtime_entry_ms',
    'sdk_rpc_lock_ms','sdk_roundtrip_ms','sdk_execute_ms','sdk_search_ms','sdk_profile_ms','sdk_add_ms',
    'source_enrich_ms','reader_get_ms','tokenize_ms','embedding_truncate_ms','embed_rpc_ms',
    'vdb_query_ms','vdb_get_ms','vdb_list_ms','archive_ms','hy_observe_ms','hy_recall_ms',
    'management_overlay_ms','prepare_lock_wait_ms','prepare_command_ms','prepare_observe_ms',
    'prepare_recall_ms','prepare_scenario_ms','prepare_persona_ms','prepare_total_ms'))
DETAIL_VERSION = '2'
HEADER_LIMIT = 4096
GATEWAY_STAGES = frozenset(('embed_gateway_ms','embed_gateway_lock_wait_ms','embed_bge_encode_ms'))
DETAIL_STAGES = GATEWAY_STAGES | frozenset(('embed_client_get_ms','embed_http_headers_ms',
    'vdb_query_pool_wait_ms','vdb_query_backend_ms'))
STAGES = LEGACY_STAGES


class Observation:
    def __init__(self, trace_id, *, detail=False):
        if not isinstance(trace_id,str) or re.fullmatch(r'[0-9a-f]{24,32}',trace_id) is None:
            raise ValueError('hy_observation_identity_invalid')
        self.trace_id = trace_id
        self.stages = {}
        self.detail_enabled = detail is True
        self.detail_stages = {}
        self.detail_available = False

    def add(self, stage, milliseconds, *, calls=1):
        target=(self.stages if stage in STAGES else self.detail_stages
                if self.detail_enabled and stage in DETAIL_STAGES else None)
        if (target is None or type(milliseconds) not in (float,int)
                or not 0 <= milliseconds <= 3600000 or not math.isfinite(milliseconds)
                or type(calls) is not int or not 1 <= calls <= 100000):
            return
        item=target.setdefault(stage,{'calls':0,'total_ms':0.0})
        item['calls']+=calls
        item['total_ms']=round(item['total_ms']+milliseconds,3)
        if target is self.detail_stages:
            self.detail_available=True

    def runtime_event(self, payload):
        if payload.get('round_id') != self.trace_id:
            return
        timings=payload.get('timings_ms',{})
        self.add('runtime_outer_lock_ms',timings.get('outer_lock_wait_ms'))
        self.add('runtime_entry_ms',timings.get('total_ms'))

    @contextmanager
    def activate(self):
        token=CURRENT.set(self)
        try: yield self
        finally: CURRENT.reset(token)

    def snapshot(self):
        return {'version':1,'trace_id':self.trace_id,
                'stages':{key:dict(value) for key,value in sorted(self.stages.items())}}

    def merge(self, value):
        if not valid_snapshot(value,self.trace_id):
            return
        for key,item in value['stages'].items():
            self.add(key,item['total_ms'],calls=item['calls'])

    def detail_snapshot(self):
        if not self.detail_enabled or not self.detail_available:
            return None
        return {'version':2,'trace_id':self.trace_id,
                'stages':{key:dict(value) for key,value in sorted(self.detail_stages.items())}}

    def merge_detail(self, value, *, allowed=DETAIL_STAGES):
        if not self.detail_enabled or not valid_detail(value,self.trace_id,allowed=allowed):
            return
        self.detail_available=True
        for key,item in value['stages'].items():
            self.add(key,item['total_ms'],calls=item['calls'])


def valid_snapshot(value, trace_id):
    return _valid(value,trace_id,1,STAGES)


def valid_detail(value, trace_id, *, allowed=DETAIL_STAGES):
    return _valid(value,trace_id,2,allowed)


def _valid(value, trace_id, version, stages):
    return (isinstance(value,dict) and set(value)=={'version','trace_id','stages'}
        and type(value['version']) is int and value['version']==version and value['trace_id']==trace_id
        and isinstance(value['stages'],dict) and not set(value['stages'])-stages
        and all(isinstance(item,dict) and set(item)=={'calls','total_ms'}
                and type(item['calls']) is int and 1<=item['calls']<=100000
                and type(item['total_ms']) in (int,float) and 0<=item['total_ms']<=3600000
                and math.isfinite(item['total_ms']) for item in value['stages'].values()))


@contextmanager
def span(stage):
    observation=CURRENT.get()
    if observation is None or (stage in DETAIL_STAGES and not observation.detail_enabled):
        yield
        return
    started=perf_counter()
    try: yield
    finally: observation.add(stage,max(0,perf_counter()-started)*1000)


def _encode(snapshot):
    if snapshot is None:
        return ''
    result=json.dumps(snapshot,separators=(',',':'),sort_keys=True)
    return result if len(result)<=HEADER_LIMIT else ''


def header(observation):
    return _encode(observation.snapshot())


def detail_header(observation):
    return _encode(observation.detail_snapshot())


def response_headers(observation):
    if observation is None:
        return {}
    base=header(observation)
    result={'X-Memory-Observation':base}
    detail=detail_header(observation)
    # 两包共享既有4096字符的观测值预算；超额仅丢详情，基础包不变。
    if detail and len(base)+len(detail)<=HEADER_LIMIT:
        result['X-Memory-Observation-Detail']=detail
    return result


def embedding_observation(value, version):
    """只复用既有匿名关联；坏header关闭旁路，不改变embedding成功/失败。"""
    try:
        return Observation(value,detail=True) if version==DETAIL_VERSION and isinstance(value,str) and len(value)<=32 else None
    except ValueError:
        return None


def merge_embedding_header(observation, value):
    """只接受同轮、固定网关阶段；不透传任意header/正文/异常详情。"""
    if observation is None or not observation.detail_enabled or not isinstance(value,str) or len(value)>HEADER_LIMIT:
        return
    try:
        snapshot=json.loads(value)
        observation.merge_detail(snapshot,allowed=GATEWAY_STAGES)
    except (ValueError,TypeError,RecursionError):
        pass


@contextmanager
def observed_lock(lock, stage):
    observation=CURRENT.get()
    if observation is None or (stage in DETAIL_STAGES and not observation.detail_enabled):
        with lock:
            yield
        return
    started=perf_counter()
    with lock:
        observation.add(stage,max(0,perf_counter()-started)*1000)
        yield


def measured(stage):
    def decorate(function):
        @wraps(function)
        def call(*args,**kwargs):
            with span(stage):
                return function(*args,**kwargs)
        return call
    return decorate
