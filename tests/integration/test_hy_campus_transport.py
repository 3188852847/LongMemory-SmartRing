"""真实HTTP及既有3.10 SDK，远端仅合成loopback；不读任何私有档案。"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Thread
from threading import Event
from time import monotonic

import pytest

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.model_gateway import ModelGateway


class Encoder:
    identity = "f" * 64


@contextmanager
def upstream(status=200, *, include_usage=True):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.path, body))
            self.send_response(status); self.send_header('Content-Type','text/event-stream'); self.end_headers()
            if status != 200:
                self.wfile.write(b'{"error":{"code":"synthetic_rejected"}}'); return
            packets = [{'id':'synthetic','object':'chat.completion.chunk','created':0,'model':'DeepSeek-V4-Flash',
                'choices':[{'index':0,'delta':{'content':'合成片段','tool_calls':[{'index':0,'id':'call_1','type':'function','function':{'name':'direct_answer','arguments':'{"response":"'}}]},'finish_reason':None}]},
                {'id':'synthetic','object':'chat.completion.chunk','created':0,'model':'DeepSeek-V4-Flash',
                'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':'合成"}'}}]},'finish_reason':None}]},
                {'id':'synthetic','object':'chat.completion.chunk','created':0,'model':'DeepSeek-V4-Flash','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            if include_usage:
                packets.append({'id':'synthetic','object':'chat.completion.chunk','created':0,'model':'DeepSeek-V4-Flash','choices':[],
                    'usage':{'prompt_tokens':10,'completion_tokens':3,'total_tokens':13}})
            for packet in packets:
                self.wfile.write(b'data: '+json.dumps(packet).encode()+b'\n\n');self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever);thread.start()
    try:yield server.server_port,calls
    finally:server.shutdown();server.server_close();thread.join(5)


def gateway(root, port):
    model=ModelSettings(provider='openai_compatible',base_url=f'http://127.0.0.1:{port}/synthetic/v1',
        api_key='synthetic-campus-key',model='DeepSeek-V4-Flash',allow_http=True,max_tokens=512,timeout_seconds=30)
    calls=FreeCampusCalls(root/'free.sqlite3',proof={'request_model':model.model,'source':'owner_confirmation'},create=True)
    return ModelGateway(settings=model,budget=calls,encoder=Encoder(),free_policy_verified=True),calls


@pytest.mark.parametrize('include_usage',[True,False])
def test_http_prefix_port_model_tools_and_unknown_usage_do_not_create_paid_reservation(tmp_path,include_usage):
    import http.client
    with upstream(include_usage=include_usage) as (port,received):
        server,calls=gateway(tmp_path,port)
        with server:
            settings=server.local_settings('voice',max_tokens=512)
            assert settings.model=='DeepSeek-V4-Flash' and settings.timeout_seconds==30
            for _ in range(2):
                connection=http.client.HTTPConnection('127.0.0.1',server.server.server_port,timeout=5)
                connection.request('POST','/voice/v1/chat/completions',body=json.dumps({'model':settings.model,'messages':[],
                    'max_tokens':512,'stream':True}),headers={'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
                response=connection.getresponse();assert response.status==200
                data=response.read();assert b'[DONE]' in data and b'tool_calls' in data;connection.close()
        assert len(received)==2 and all(path=='/synthetic/v1/chat/completions' for path,_ in received)
        assert all(body['model']=='DeepSeek-V4-Flash' and body['max_tokens']==512 for _,body in received)
        status=calls.status();assert status['state']=='available' and status['attempt_count']==2
        assert status['personal_cost_micro_cny']==0 and status['unknown_or_inflight']==(0 if include_usage else 2)
        with sqlite3.connect(calls.path) as connection:
            failures=connection.execute('SELECT failure FROM gateway_results').fetchall()
            assert failures==[(None if include_usage else 'missing_usage',)]*2


SDK=Path(os.environ.get('LONGMEMORY_TEST_XIAOZHI_PYTHON','missing'))
VENDOR=Path('D:/03-项目/01-正式项目/智慧圆屏/local/runtime/xiaozhi-esp32-server/main/xiaozhi-server/core/providers/llm/openai/openai.py')
@pytest.mark.skipif(not SDK.is_file() or not VENDOR.is_file(),reason='explicit installed voice SDK/source required')
@pytest.mark.parametrize('upstream_status',[200,400])
def test_actual_vendor_provider_and_python310_sdk_do_not_retry_and_drain_usage(tmp_path,upstream_status):
    child=r'''
import sys,types,importlib.util,json
sys.path.insert(0,sys.argv[1])
class Logger:
    def __getattr__(self,name):return lambda *args,**kwargs:self
logger=types.ModuleType('config.logger');logger.setup_logging=lambda *args:Logger();sys.modules['config.logger']=logger
util=types.ModuleType('core.utils.util');util.check_model_key=lambda *args:None;sys.modules['core.utils.util']=util
base=types.ModuleType('core.providers.llm.base');base.LLMProviderBase=object;sys.modules['core.providers.llm.base']=base
spec=importlib.util.spec_from_file_location('synthetic_vendor',sys.argv[2]);provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(provider)
from voice_budget import install_no_retry_gateway_client
install_no_retry_gateway_client(provider)
llm=provider.LLMProvider({'base_url':sys.argv[3],'api_key':sys.argv[4],'model_name':'DeepSeek-V4-Flash','max_tokens':512,'timeout':30})
assert llm.client.max_retries==0
try:
    rows=list(llm.response_with_functions('synthetic',[{'role':'user','content':'合成问题'}]))
    assert any(row[1] for row in rows)
    print(json.dumps({'ok':True,'retries':llm.client.max_retries}))
except Exception as error:print(json.dumps({'ok':False,'status':getattr(error,'status_code',None),'retries':llm.client.max_retries}))
finally:llm.client.close()
'''
    with upstream(upstream_status) as (port,received):
        server,calls=gateway(tmp_path,port)
        with server:
            result=subprocess.run([str(SDK),'-X','utf8','-B','-c',child,str(Path(__file__).resolve().parents[2]/'scripts/development/xiaozhi'),
                str(VENDOR),server.base+'/voice/v1',server.token],capture_output=True,text=True,timeout=15,check=True)
            value=json.loads(result.stdout.strip())
        assert len(received)==1 and value['retries']==0 and value['ok']==(upstream_status==200)
        if upstream_status!=200:assert value['status']==502
        assert calls.status()['unknown_or_inflight']==(0 if upstream_status==200 else 1)
        with sqlite3.connect(calls.path) as connection:
            assert connection.execute('SELECT status,failure FROM gateway_results').fetchone()==(
                upstream_status,None if upstream_status==200 else 'provider_http_error')


def test_close_interrupts_http10_stream_and_restart_preserves_unknown(tmp_path):
    import http.client
    release=Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"synthetic"}}]}\n\n');self.wfile.flush()
            release.wait(5)
    provider=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=provider.serve_forever);thread.start()
    server,calls=gateway(tmp_path,provider.server_port)
    connection=None
    try:
        server.__enter__()
        connection=http.client.HTTPConnection('127.0.0.1',server.server.server_port,timeout=5)
        connection.request('POST','/voice/v1/chat/completions',body=json.dumps({'model':'DeepSeek-V4-Flash',
            'messages':[],'max_tokens':512,'stream':True}),headers={'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
        response=connection.getresponse();assert response.status==200 and b'synthetic' in response.readline()
        started=monotonic();server.close();assert monotonic()-started<2
        with sqlite3.connect(calls.path) as db:
            assert db.execute('SELECT failure FROM gateway_results').fetchone()==('gateway_closed',)
        reopened=FreeCampusCalls(calls.path,proof=calls.proof)
        assert reopened.status()['unknown_or_inflight']==1
        assert reopened.status()['personal_cost_micro_cny']==0
    finally:
        release.set();server.close()
        if connection:connection.close()
        provider.shutdown();provider.server_close();thread.join(5)
