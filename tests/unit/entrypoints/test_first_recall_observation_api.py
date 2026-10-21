"""直接执行实际API路由的协商分支；合成后端，无监听端口。"""

import asyncio
from dataclasses import dataclass
import json
from types import SimpleNamespace as NS

from aiohttp import web
import pytest

from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
from longmemory.methods.hy_memory.observation import CURRENT, span, valid_snapshot,valid_detail


@dataclass
class Timings:
    lock_wait_ms:float=0
    command_ms:float=0
    observe_ms:float=0
    recall_ms:float=0
    scenario_ms:float=0
    persona_ms:float=0
    total_ms:float=0


@pytest.mark.parametrize('requested',[{}, {'X-Memory-Observe-Detail':'2'},
    {'X-Memory-Observe':'1'}, {'X-Memory-Observe':'1','X-Memory-Observe-Detail':'3'},
    {'X-Memory-Observe':'1','X-Memory-Observe-Detail':'2'}])
@pytest.mark.parametrize('fail',[False,True])
def test_actual_route_preserves_body_status_and_only_emits_negotiated_detail(requested,fail):
    calls=[]
    class Backend:
        def memory_runtime(self):return NS(legacy_sqlite=False)
        def prepare_round_screen_user(self,text,**kwargs):
            calls.append(text)
            # 模拟实际协商worker返回的getter测量，不伪造API自身能力声明。
            with span('embed_client_get_ms'):pass
            if fail:raise ValueError('synthetic conflict')
            return NS(support=NS(context='private synthetic context',retrieved=[],
                retrieval_strategy='synthetic',warning_code=None),
                observation=NS(writes=[],processing_status='completed',warning_code=None),
                scenarios=[],personas=[],memory_command=None,follow_up_suggestion=None,
                temporary_interaction=None,event=NS(event_id='synthetic-turn'),timings=Timings(),
                write_enabled=False,use_enabled=True,scenario_use_enabled=False,persona_use_enabled=False),None
    class Request(dict):
        headers=requested
        def clone(self,**kwargs):return self
        async def json(self):return {'version':1,'query':'private question',
            'client_round_id':'a'*32,'session_id':'b'*32}
    app=web.Application();register_memory_runtime_routes(app,Backend())
    route=next(route for route in app.router.routes() if route.method=='POST'
        and route.resource.canonical=='/api/internal/memory/prepare')
    response=asyncio.run(route.handler(Request()))
    assert response.status==(409 if fail else 200) and calls==['private question']
    body=json.loads(response.body)
    if fail:assert body=={'error':'round_screen_prepare_conflict','version':1}
    else:assert body['context']=='private synthetic context'
    base=response.headers.get('X-Memory-Observation')
    detail=response.headers.get('X-Memory-Observation-Detail')
    assert (base is not None)==(requested.get('X-Memory-Observe')=='1')
    if base is not None:assert valid_snapshot(json.loads(base),'a'*32)
    assert (detail is not None)==(requested.get('X-Memory-Observe')=='1' and requested.get('X-Memory-Observe-Detail')=='2')
    if detail is not None:assert valid_detail(json.loads(detail),'a'*32)
    assert CURRENT.get() is None and 'private' not in str(base)+str(detail)
