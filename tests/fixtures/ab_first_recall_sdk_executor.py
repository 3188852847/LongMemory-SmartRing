"""显式SDK解释器内的真实VDB执行器取消探针；无库、模型或网络请求。"""

import asyncio
from copy import deepcopy
import json
from threading import Event

from longmemory.methods.hy_memory.observation import Observation
from longmemory.methods.hy_memory.sdk_observation import SDKObservation,_scope
from longmemory.methods.hy_memory.worker import install_network_denial

install_network_denial()
from hy_memory.data import vector_store_chroma as vector


async def run_case(mode):
    original_executor=vector._vdb_executor
    gate=Event();entered=Event();finished=Event();calls=[];blockers=[]
    if mode=='queued':
        # 只用Event占住现有执行器，不新建或替换SDK执行器。
        for _ in range(original_executor._max_workers):
            event=Event()
            def block(event=event):event.set();gate.wait(5)
            blockers.append(original_executor.submit(block))
            assert event.wait(2)
    def query():
        calls.append(1);entered.set()
        if mode=='started':assert gate.wait(5)
        try:
            if mode=='error':raise ValueError('private synthetic error')
            return 'original-result'
        finally:finished.set()
    observation=Observation('a'*32,detail=True)
    async def execute():
        with _scope('vdb_query_ms'):return await vector._run_in_vdb_pool(query)
    try:
        with observation.activate():
            task=asyncio.create_task(execute())
            await asyncio.sleep(0)
            if mode in {'queued','started'}:
                if mode=='started':
                    while not entered.is_set():await asyncio.sleep(.001)
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
                else:raise AssertionError('original cancellation was lost')
                before=deepcopy(observation.detail_snapshot())
                gate.set()
                while not finished.is_set():await asyncio.sleep(.001)
                await asyncio.sleep(.01)
                assert observation.detail_snapshot()==before
            elif mode=='error':
                try:await task
                except ValueError as error:assert str(error)=='private synthetic error'
                else:raise AssertionError('original error was lost')
            else:assert await task=='original-result'
        assert calls==[1] and vector._vdb_executor is original_executor
        keys=set(observation.detail_stages)
        assert ('vdb_query_pool_wait_ms' in keys)==(mode!='queued')
        assert ('vdb_query_backend_ms' in keys)==(mode in {'success','error'})
        return {'case':mode,'calls':len(calls),'executor_preserved':True,
            'detail':observation.detail_snapshot(),'late_mutation':False}
    finally:
        gate.set()
        for blocker in blockers:blocker.result(timeout=2)


observer=SDKObservation(sdk_version='2.0.3')
assert observer.applied
try:
    print(json.dumps({'cases':[asyncio.run(run_case(mode)) for mode in ('success','error','queued','started')]}))
finally:observer.close()
