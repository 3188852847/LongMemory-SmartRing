"""真实SDK经自有回环网关＋模拟远端；无付费网络请求。"""
from datetime import UTC,datetime
from pathlib import Path
from time import time
import hashlib
import json
import os

import pytest

from longmemory.bootstrap import build_hy_memory_runtime
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.contracts import MemoryEvent
from longmemory.methods.hy_memory.budget import PricePolicy,SharedBudget
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.settings import Endpoint,HySettings
from longmemory.methods.hy_memory.observation import Observation,DETAIL_STAGES,valid_snapshot,valid_detail

SDK=Path(os.environ.get("LONGMEMORY_TEST_HY_PYTHON",str(Path(__file__).resolve().parents[2]/"local/runtime/hy-memory/.venv/Scripts/python.exe")))


@pytest.mark.skipif(not SDK.is_file(),reason="isolated SDK missing")
def test_sdk_local_gateway_has_shared_budget_and_embedding_scope(tmp_path):
    class Encoder:
        identity="f"*64
        def encode_documents(self,texts):return [[1.0]+[0.0]*511 for _ in texts]
        def encode_query(self,text):return [1.0]+[0.0]*511
    def remote(payload):
        return 200,json.dumps({"id":"synthetic","model":"deepseek-v4-flash", "choices":[{"index":0,"finish_reason":"stop", "message":{"role":"assistant","content":json.dumps({"memory":[{"content":"合成用户喜欢茶","tags":[],"owner":"user"}],"intentions":[],"basic_info":{}})}}],"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}).encode()
    budget=SharedBudget(tmp_path/"budget.db",policy=PricePolicy(expires_at_unix=time()+3600),create=True)
    model=ModelSettings(provider="openai_compatible",base_url="https://api.deepseek.com",api_key="synthetic-not-actual",model="deepseek-v4-flash")
    with ModelGateway(settings=model,budget=budget,encoder=Encoder(),currency_verified=True,remote=remote) as gateway:
        endpoint=Endpoint(gateway.base+"/hy/v1",model.model,gateway.token,True)
        embedding=Endpoint(gateway.base+"/hy/v1",Encoder.identity,gateway.token,True)
        settings=HySettings(user_id="synthetic-gateway",llm=endpoint,embedding=embedding,
            embedding_dimensions=512,network_authorized=True,max_external_requests=200,
            managed_gateway=True,provider_identity=hashlib.sha256(b"synthetic").hexdigest())
        runtime=build_hy_memory_runtime(settings=settings,state_directory=tmp_path/"e",source_path=tmp_path/"s.db",create=True,python=SDK)
        try:
            result=runtime._method.observe(MemoryEvent("test1","user","合成用户喜欢茶",datetime(2026,1,1,tzinfo=UTC)))
            assert result.processing_status=="completed"
            assert runtime._method.recall("茶").retrieved
            diagnostics=runtime._method.engine.sdk_call("diagnostics")
            assert diagnostics["external_http_attempts"]==0 and diagnostics["local_gateway_requests"]>0
            assert budget.report()["attempt_count"]>0 and budget.report()["unknown_or_inflight"]==0
        finally:runtime.close()


@pytest.mark.skipif(not SDK.is_file(),reason="isolated SDK missing")
def test_first_recall_v2_real_sdk_owned_executor_and_local_fake_encoder(tmp_path):
    """空合成库首次召回；随机回环网关，拒绝任何LLM/供应商调用。"""
    class Encoder:
        identity='f'*64
        def encode_documents(self,texts):return [[1.0]+[0.0]*511 for _ in texts]
        def encode_query(self,text):return [1.0]+[0.0]*511
    def remote(payload):pytest.fail('first recall must not call a model provider')
    budget=SharedBudget(tmp_path/'budget.db',policy=PricePolicy(expires_at_unix=time()+3600),create=True)
    model=ModelSettings(provider='openai_compatible',base_url='https://example.invalid',
        api_key='synthetic',model='deepseek-v4-flash')
    with ModelGateway(settings=model,budget=budget,encoder=Encoder(),currency_verified=True,remote=remote) as gateway:
        settings=HySettings(user_id='synthetic-v2-first-recall',
            llm=Endpoint(gateway.base+'/hy/v1',model.model,gateway.token,True),
            embedding=Endpoint(gateway.base+'/hy/v1',Encoder.identity,gateway.token,True),
            embedding_dimensions=512,network_authorized=True,max_external_requests=200,
            managed_gateway=True,provider_identity=hashlib.sha256(b'synthetic-v2').hexdigest())
        runtime=build_hy_memory_runtime(settings=settings,state_directory=tmp_path/'state',
            source_path=tmp_path/'source.db',create=True,python=SDK)
        try:
            detailed=Observation('a'*32,detail=True)
            with detailed.activate():first=runtime._method.recall('合成首次查询甲')
            assert valid_snapshot(detailed.snapshot(),detailed.trace_id)
            assert valid_detail(detailed.detail_snapshot(),detailed.trace_id)
            assert set(detailed.detail_stages)==DETAIL_STAGES
            assert not first.retrieved
            first_calls=gateway.embedding_calls
            ordinary=Observation('b'*32)
            with ordinary.activate():second=runtime._method.recall('合成首次查询乙')
            assert not second.retrieved and second.warning_code==first.warning_code
            assert ordinary.detail_snapshot() is None
            assert gateway.embedding_calls==2*first_calls and first_calls>0
            assert all(stage not in detailed.stages for stage in DETAIL_STAGES)
            assert all(item['calls']>0 for item in detailed.detail_stages.values())
            assert budget.report()['attempt_count']==0
            diagnostics=runtime._method.engine.sdk_call('diagnostics')
            assert diagnostics['external_http_attempts']==0
        finally:runtime.close()
