"""自有回环HTTP网关显式详情协议；无SDK/BGE或远端调用。"""

import json
from time import time
from urllib import request,error

import pytest

from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.budget import PricePolicy,SharedBudget
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.observation import GATEWAY_STAGES,valid_detail


def test_gateway_auth_version_and_trace_only_control_optional_detail_header(tmp_path):
    class Encoder:
        identity='f'*64
        def encode_query(self,text):return [1.0,0.0]
    budget=SharedBudget(tmp_path/'budget.db',policy=PricePolicy(expires_at_unix=time()+3600),create=True)
    model=ModelSettings(provider='openai_compatible',base_url='https://example.invalid',api_key='synthetic',model='deepseek-v4-flash')
    def remote(payload):pytest.fail('must not forward any observation to model provider')
    with ModelGateway(settings=model,budget=budget,encoder=Encoder(),currency_verified=True,remote=remote) as gateway:
        results=[]
        for auth,version,trace,status in ((False,'2','a'*32,401),(True,None,'a'*32,200),
                (True,'1','a'*32,200),(True,'2','private',200),(True,'2','a'*32,200)):
            headers={'Content-Type':'application/json','X-Hy-Embedding-Role':'query','X-Hy-Observation-Id':trace}
            if auth:headers['Authorization']='Bearer '+gateway.token
            if version is not None:headers['X-Hy-Observe-Detail']=version
            req=request.Request(gateway.base+'/hy/v1/embeddings',
                data=json.dumps({'model':Encoder.identity,'input':'private synthetic query'}).encode(),headers=headers)
            try:response=request.build_opener(request.ProxyHandler({})).open(req,timeout=3)
            except error.HTTPError as caught:response=caught
            with response:
                assert response.status==status
                body=json.loads(response.read())
                detail=response.headers.get('X-Hy-Observation-Detail')
                assert response.headers.get('X-Hy-Observation') is None
                enabled=auth and version=='2' and trace=='a'*32
                assert (detail is not None)==enabled
                if enabled:
                    packet=json.loads(detail)
                    assert valid_detail(packet,trace,allowed=GATEWAY_STAGES)
                    assert set(packet['stages'])==GATEWAY_STAGES and len(detail)<=4096
                if status==200:results.append(body)
                assert 'private' not in str(detail)
        assert all(result==results[0] for result in results)
        assert gateway.embedding_calls==4 and budget.report()['attempt_count']==0
