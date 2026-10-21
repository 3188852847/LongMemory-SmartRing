"""一次请求的固定数值观测；跨进程只传匿名关联，不传业务正文。"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import math
import re
from time import perf_counter


CURRENT = ContextVar('hy_request_observation', default=None)
STAGES = frozenset(('api_queue_ms','api_prepare_ms','runtime_outer_lock_ms','runtime_entry_ms',
    'sdk_rpc_lock_ms','sdk_roundtrip_ms','sdk_execute_ms','sdk_search_ms','sdk_profile_ms','sdk_add_ms',
    'source_enrich_ms','reader_get_ms','tokenize_ms','embedding_truncate_ms','embed_rpc_ms',
    'vdb_query_ms','vdb_get_ms','vdb_list_ms','archive_ms','hy_observe_ms','hy_recall_ms',
    'management_overlay_ms','prepare_lock_wait_ms','prepare_command_ms','prepare_observe_ms',
    'prepare_recall_ms','prepare_scenario_ms','prepare_persona_ms','prepare_total_ms'))


class Observation:
    def __init__(self, trace_id):
        if not isinstance(trace_id,str) or re.fullmatch(r'[0-9a-f]{24,32}',trace_id) is None:
            raise ValueError('hy_observation_identity_invalid')
        self.trace_id = trace_id
        self.stages = {}

    def add(self, stage, milliseconds, *, calls=1):
        if (stage not in STAGES or type(milliseconds) not in (float,int)
                or not 0 <= milliseconds <= 3600000 or not math.isfinite(milliseconds)
                or type(calls) is not int or not 1 <= calls <= 100000):
            return
        item=self.stages.setdefault(stage,{'calls':0,'total_ms':0.0})
        item['calls']+=calls
        item['total_ms']=round(item['total_ms']+milliseconds,3)

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


def valid_snapshot(value, trace_id):
    return (isinstance(value,dict) and set(value)=={'version','trace_id','stages'}
        and type(value['version']) is int and value['version']==1 and value['trace_id']==trace_id
        and isinstance(value['stages'],dict) and not set(value['stages'])-STAGES
        and all(isinstance(item,dict) and set(item)=={'calls','total_ms'}
                and type(item['calls']) is int and 1<=item['calls']<=100000
                and type(item['total_ms']) in (int,float) and 0<=item['total_ms']<=3600000
                and math.isfinite(item['total_ms']) for item in value['stages'].values()))


@contextmanager
def span(stage):
    observation=CURRENT.get()
    if observation is None:
        yield
        return
    started=perf_counter()
    try: yield
    finally: observation.add(stage,max(0,perf_counter()-started)*1000)


def header(observation):
    result=json.dumps(observation.snapshot(),separators=(',',':'),sort_keys=True)
    return result if len(result)<=4096 else ''


def measured(stage):
    def decorate(function):
        @wraps(function)
        def call(*args,**kwargs):
            with span(stage):
                return function(*args,**kwargs)
        return call
    return decorate
