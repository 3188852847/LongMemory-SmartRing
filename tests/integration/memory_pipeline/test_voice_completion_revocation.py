"""固定ASR/chat＋真实MemoryProvider合成回执，candidate OFF也保护撤权后的归档。"""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from tests.integration.memory_pipeline.test_xiaozhi_bridge import provider_class, config

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('phase', ['queued_before_prepare', 'after_prepare'])
def test_revoked_turn_never_completes_after_abort_bool_reset(provider_class, config, monkeypatch, phase):
    if not os.environ.get('LONGMEMORY_TEST_XIAOZHI_ROOT'):
        pytest.skip('explicit existing native repository required; never download')
    monkeypatch.syspath_prepend(str(ROOT/'scripts/development/xiaozhi'))
    monkeypatch.syspath_prepend(str(ROOT/'tests/fixtures'))
    import launch_with_memory as launch
    import voice_interruption_upstream as upstream
    spec=importlib.util.spec_from_file_location('completion_native_boundary',ROOT/'tests/fixtures/voice_proposal_adapter_native.py')
    boundary=importlib.util.module_from_spec(spec);spec.loader.exec_module(boundary)
    calls=[]
    class Response:
        status=200
        headers={}
        def __init__(self,value):self.value=value
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,_limit):return json.dumps(self.value).encode()
    def request(req,timeout):
        body=json.loads(req.data);calls.append((req.full_url,body))
        if req.full_url.endswith('/prepare'):
            return Response({'version':1,'memory_protocol':2,'turn_id':str(uuid4()),'added':None,'retrieved':None,
                'context':'合成记忆','memory_receipt':{'retrieved_count':None,'retrieval_strategy':None,'evidence':None}})
        if req.full_url.endswith('/cancel'):return Response({'version':1,'state':'cancelled'})
        return Response({'version':1,'assistant_event_id':str(uuid4()),'created':True,'playback_acknowledgement':'unavailable'})
    monkeypatch.setenv('LONGMEMORY_MEMORY_TRANSPORT','runtime')
    monkeypatch.setenv('LONGMEMORY_RUNTIME_URL','http://127.0.0.1:23456/api/internal/memory/prepare')
    monkeypatch.setenv('LONGMEMORY_RUNTIME_TOKEN','f'*64)
    monkeypatch.setattr('urllib.request.urlopen',request)
    provider=provider_class(config);provider.init_memory(config['allowed_device_id'],None)
    async def run():
        h=boundary.harness(install_adapter=False)
        u=upstream.build()
        h.connection.memory=provider
        h.connection.tts._longmemory_cosy_streaming_installed=True
        h.connection.tts.current_sentence_id='synthetic-old'
        h.connection.sample_rate=16000
        h.connection.client_aec=True
        h.connection.client_listen_mode='realtime'
        h.connection.clearSpeakStatus=u.conn.clearSpeakStatus.__func__.__get__(h.connection,type(h.connection))
        async def send(_value):pass
        h.connection.websocket=NS(send=send)
        h.native.receive.handleAbortMessage=u.receive.handleAbortMessage
        monkeypatch.setitem(__import__('sys').modules,'core.handle',NS(sendAudioHandle=u.send))
        monkeypatch.setitem(__import__('sys').modules,'core.providers.tts',NS(base=u.ttsbase))
        entered,release=threading.Event(),threading.Event()
        invocations=[]
        class LLM:
            def response(self,*args,**kwargs):
                invocations.append(True)
                if phase=='after_prepare' and len(invocations)==1:
                    entered.set();assert release.wait(5)
                    yield '被撤权的旧合成回答'
                else:yield '新合成回答'
        h.connection.llm=LLM()
        launch.install_answer_completion(type(h.connection))
        result=launch.install_voice_output_revocation_policy(type(h.connection),h.native.receive,h.native.base)
        assert result['requires_preemptive'] is False
        assert not hasattr(type(h.connection),'_longmemory_proposal_adapter')
        try:
            await boundary.begin(h)
            if phase=='queued_before_prepare':h.executor.release.clear()
            await boundary.endpoint(h)
            if phase=='after_prepare':
                assert await asyncio.to_thread(entered.wait,3)
                assert len([x for x in calls if x[0].endswith('/prepare')])==1
                h.executor.release.clear()
            h.connection.client_is_speaking=True
            h.connection.client_have_voice=True
            h.connection.vad_last_voice_time=boundary.time.time()*1000-300
            # 播放期间原prefetch主动跳过，第二次必须走完整的原生ASR交接。
            for _ in range(16):await h.provider.receive_audio(h.connection,boundary.PCM,True)
            await boundary.endpoint(h)
            assert h.connection.client_abort is False  # 原生startToChat已复位，不能借该布尔阻挡归档。
            if phase=='after_prepare':
                assert h.connection._longmemory_active_completion['superseded'] is False
                release.set();await asyncio.wrap_future(h.executor.futures[0])
                assert not any(x[0].endswith('/complete') for x in calls)
            h.executor.release.set()
            for future in h.executor.futures:await asyncio.wrap_future(future)
            prepares=[b for url,b in calls if url.endswith('/prepare')]
            completions=[b for url,b in calls if url.endswith('/complete')]
            cancellations=[b for url,b in calls if url.endswith('/cancel')]
            assert len(prepares)==(2 if phase=='after_prepare' else 1)
            assert len(cancellations)==(1 if phase=='after_prepare' else 0)
            assert len(completions)==1 and completions[0]['answer']=='新合成回答'
            assert not provider._pending_completions
            assert [row.content for row in h.connection.dialogue.dialogue if row.role=='assistant']==['新合成回答']
            assert not h.connection.logger.errors
        finally:
            release.set();h.executor.release.set()
            for future in h.executor.futures:await asyncio.wrap_future(future)
            await h.connection.close();h.executor.shutdown(wait=True)
    asyncio.run(run())
