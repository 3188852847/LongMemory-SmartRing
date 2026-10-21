"""同规模轻量合成开关对照；不代表真实SDK/HTTP/BGE或首次延迟。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime,timezone
import json
import platform
from statistics import median
from threading import Lock
from time import perf_counter

from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.observation import Observation,span
from longmemory.methods.hy_memory.sdk_observation import _wrap,_wrap_vdb_pool


async def probe():
    class Encoder:
        identity='f'*64
        def encode_query(self,text):return [1.0,0.0]
    gateway=object.__new__(ModelGateway);gateway.encoder=Encoder();gateway._embedding_lock=Lock()
    gateway.embedding_calls=gateway.embedding_inputs=0
    backend_calls=[0];getter_calls=[0]
    def getter():getter_calls[0]+=1;return gateway
    get_client=_wrap(getter,'embed_client_get_ms')
    with ThreadPoolExecutor(max_workers=1) as executor:
        async def original_pool(func,*args,**kwargs):
            return await asyncio.get_running_loop().run_in_executor(executor,lambda:func(*args,**kwargs))
        pool=_wrap_vdb_pool(original_pool)
        def query():backend_calls[0]+=1;return ()
        async def search():return await pool(query)
        observed_search=_wrap(search,'vdb_query_ms')
        async def one(mode):
            observation=None if mode=='off' else Observation('a'*32,detail=mode=='detail')
            with observation.activate() if observation is not None else nullcontext():
                client=get_client()
                # 合成直调跨度，只测包装开销；这里没有真实HTTP收发。
                with span('embed_http_headers_ms'):
                    client.embed({'model':Encoder.identity,'input':'synthetic'},'query')
                assert await observed_search()==()
        for mode in ('off','base','detail'):
            for _ in range(20):await one(mode)
        samples={mode:[] for mode in ('off','base','detail')}
        counts={mode:[] for mode in samples}
        batch_size=60;batches=9
        for batch in range(batches):
            order=('off','base','detail')
            order=order[batch%3:]+order[:batch%3]
            for mode in order:
                before=(getter_calls[0],gateway.embedding_calls,backend_calls[0]);started=perf_counter()
                for _ in range(batch_size):await one(mode)
                samples[mode].append(round((perf_counter()-started)*1e6/batch_size,3))
                counts[mode].append([after-old for after,old in zip(
                    (getter_calls[0],gateway.embedding_calls,backend_calls[0]),before)])
        assert all(count==[batch_size]*3 for values in counts.values() for count in values)
        medians={mode:round(median(values),3) for mode,values in samples.items()}
        return {'kind':'synthetic_wrapper_overhead_not_production_latency',
            'timestamp_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
            'model':'fake two-dimensional encoder; no SDK/BGE/HTTP/RPC/GPU',
            'batch_size':batch_size,'batches':batches,'warmups_per_mode':20,'samples_us_per_call':samples,
            'median_us_per_call':medians,'detail_minus_base_median_us':round(medians['detail']-medians['base'],3),
            'all_modes_same_getter_embedding_backend_counts':True,
            'limit':'Includes Python wrappers and one dedicated synthetic executor; excludes real latency and numerical error bound.'}


if __name__=='__main__':print(json.dumps(asyncio.run(probe()),sort_keys=True))
