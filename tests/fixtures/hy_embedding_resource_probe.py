"""固定SDK搜索loop的首次embed探针；随机回环替身，无LLM/BGE或个人库。"""

import cProfile
import hashlib
from importlib.metadata import version
import json
import logging
import os
from pathlib import Path
import pstats
import sys
import threading
from time import perf_counter
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

logging.disable(logging.CRITICAL)

from longmemory.methods.hy_memory import sdk_observation
from longmemory.methods.hy_memory.worker import create_sdk,ProtocolService
from longmemory.methods.hy_memory.settings import Endpoint,HySettings
from longmemory.methods.hy_memory.observation import Observation


def run(mode, *, profile_enabled=False):
    if mode not in {'baseline','prepared'}:
        raise ValueError('synthetic_probe_mode_invalid')
    if os.environ.get('PYTHON_DOTENV_DISABLED')!='1':
        raise ValueError('synthetic_probe_requires_clean_worker_environment')
    def deny_private_config(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)):
            path=os.fsdecode(args[0]).replace('\\','/').lower()
            if path.rsplit('/',1)[-1]=='.env' or '/local/config/' in path:
                raise PermissionError('synthetic_probe_private_config_denied')
    # SDK自己的dotenv扫描不遵守标准dotenv开关；进程级审计另拒绝真实配置读取。
    sys.addaudithook(deny_private_config)
    counts={'embedding':0,'other':0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path!='/hy/v1/embeddings':
                counts['other']+=1;self.send_error(400);return
            counts['embedding']+=1
            texts=body['input'] if isinstance(body['input'],list) else [body['input']]
            payload=json.dumps({'object':'list','model':'synthetic','data':[
                {'object':'embedding','index':i,'embedding':[1.0]+[0.0]*511}
                for i in range(len(texts))]}).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers();self.wfile.write(payload)

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    if server.server_port in {8766,8767,8768,8000,8003,18767,18768,18769,18770}:
        server.server_close();raise ValueError('synthetic_probe_daily_port_rejected')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    endpoint=Endpoint('http://127.0.0.1:'+str(server.server_port)+'/hy/v1',
        'synthetic','synthetic',True)
    settings=HySettings(user_id='synthetic-resource-probe',llm=endpoint,embedding=endpoint,
        embedding_dimensions=512,network_authorized=True,max_external_requests=10,
        managed_gateway=True,provider_identity='a'*64)
    workspace=Path('state').resolve();workspace.mkdir()
    def files():
        return {path.relative_to(workspace).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in workspace.rglob('*') if path.is_file()}

    original_prepare=sdk_observation.SDKObservation.prepare_local_backends
    original_import=sdk_observation.importlib.import_module
    preparation={}
    def legacy_import(name,*args,**kwargs):
        # 只在准备阶段省掉新增的公开资源导入，保留旧e4的其他真实准备行为。
        # 不添加生产开关；查询开始前恢复真实importlib。
        if name=='openai.resources.embeddings':return SimpleNamespace(AsyncEmbeddings=object)
        return original_import(name,*args,**kwargs)
    def checked_prepare(observer):
        before=files();started=perf_counter()
        preparation['resources_loaded_before']='openai.resources.embeddings' in sys.modules
        try:
            if mode=='baseline':sdk_observation.importlib.import_module=legacy_import
            result=original_prepare(observer)
        finally:sdk_observation.importlib.import_module=original_import
        preparation.update(wall_ms=round((perf_counter()-started)*1000,3),
            files_unchanged=before==files(),http_requests=dict(counts),
            resources_loaded_after='openai.resources.embeddings' in sys.modules,result=result)
        assert preparation['files_unchanged'] and counts=={'embedding':0,'other':0}
        return result

    client=budget=None
    try:
        sdk_observation.SDKObservation.prepare_local_backends=checked_prepare
        try:client,budget=create_sdk(settings,workspace,create=True)
        finally:sdk_observation.SDKObservation.prepare_local_backends=original_prepare
        preparation['client_cache_entries']=len(client._embed_service._client_cache)
        preparation['vector_cache_entries']=len(client._embed_service._cache)
        assert preparation['client_cache_entries']==preparation['vector_cache_entries']==0
        budget.operation='search'

        async def sample(index):
            observation=Observation(('a' if index==0 else 'b')*32,detail=True)
            profiler=cProfile.Profile();started=perf_counter()
            with observation.activate():
                if profile_enabled:profiler.enable()
                try:
                    # 对齐worker语义分支的同一入口；不同合成输入且禁用结果缓存。
                    vector=await client._embed_service.embed('synthetic-'+str(index),use_cache=False)
                finally:
                    if profile_enabled:profiler.disable()
            elapsed=(perf_counter()-started)*1000
            assert vector==[1.0]+[0.0]*511
            rows=[]
            if profile_enabled:
                for (filename,line,name),(cc,nc,tt,ct,callers) in pstats.Stats(profiler).stats.items():
                    if ct<=.005:continue
                    path=filename.replace('\\','/')
                    path=path.split('/site-packages/',1)[-1] if '/site-packages/' in path else Path(filename).name
                    rows.append({'file':path,'line':line,'name':name,'calls':nc,
                        'self_ms':round(tt*1000,3),'cumulative_ms':round(ct*1000,3)})
            return {'total_ms':round(elapsed,3),'base':observation.snapshot(),
                'detail':observation.detail_snapshot(),
                'profile':sorted(rows,key=lambda row:row['cumulative_ms'],reverse=True)[:45]}

        samples=[client._search_loop_thread.run(sample(i)) for i in range(2)]
        assert counts=={'embedding':2,'other':0}
        return {'kind':'synthetic_sdk_embedding_resource_probe','mode':mode,
            'profile_enabled':profile_enabled,'versions':{name:version(name) for name in
                ('hy-memory','openai','pydantic','httpx')},'preparation':preparation,
            'counts':counts,'external_http_attempts':budget.report()['external_http_attempts'],
            'local_gateway_requests':budget.local_gateway_requests,'samples':samples}
    finally:
        sdk_observation.importlib.import_module=original_import
        sdk_observation.SDKObservation.prepare_local_backends=original_prepare
        if client is not None:
            service=ProtocolService();service.client=client;service.budget=budget;service.settings=settings
            service.execute('close',{})
        server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':
    print(json.dumps(run(sys.argv[1],profile_enabled='--profile' in sys.argv)))
