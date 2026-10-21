"""仅固定2.0.3独占worker内包装观测引用；不改安装目录、不主动执行SDK。"""

from functools import wraps
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import inspect
import importlib
from pathlib import Path
from time import perf_counter
from threading import Lock

from .observation import CURRENT, span

_VDB_QUERY = ContextVar('hy_observed_vdb_query',default=False)


SOURCES = {
    'pipelines/registry.py':'f0d1c45de64ebe181de62c4571fd87a788cfd9addab143300b32cdcf6d3e2850',
    'pipelines/reader_base.py':'edbb334709b0c56007d8cd74197062d4c2f6e5084c0c4143517881988f4401f8',
    'pipelines/_retrieval/lemmatize.py':'c7eee75fe45f8ddcc7d118f1532680c88cd9f5b3e9fe7f762caa1ddc729102da',
    'core/embed_service.py':'19a929f5a5c8b2d8c8266a594cc1c1be0ec5861e60b858ca5a380453096cf905',
    'data/vector_store_chroma.py':'a3be99b273da02aa1ce860376886de76079e3c061400dc039c2408f69c4b1a33',
    'utils/async_executor.py':'7ec5900601914bc3468130d13e6426c1a511cfb0c7c69df394996ea91036e5cb',
}


@contextmanager
def _scope(stage):
    observation=CURRENT.get()
    token=(_VDB_QUERY.set(True) if stage=='vdb_query_ms' and observation is not None
           and observation.detail_enabled else None)
    try:
        with span(stage):
            yield
    finally:
        if token is not None:
            _VDB_QUERY.reset(token)


def _wrap(original, stage):
    if inspect.iscoroutinefunction(original):
        @wraps(original)
        async def call(*args,**kwargs):
            with _scope(stage):
                return await original(*args,**kwargs)
    else:
        @wraps(original)
        def call(*args,**kwargs):
            with _scope(stage):
                return original(*args,**kwargs)
    return call


def _wrap_vdb_pool(original):
    """保留原executor/cancel策略；只测实际callback进入/返回，不猜Rust内部锁。"""
    @wraps(original)
    async def call(func,*args,**kwargs):
        observation=CURRENT.get()
        if observation is None or not observation.detail_enabled or not _VDB_QUERY.get():
            return await original(func,*args,**kwargs)
        submitted=perf_counter()
        times={}
        lock=Lock()
        def measured_call():
            with lock:
                times['started']=perf_counter()
            try:
                return func(*args,**kwargs)
            finally:
                with lock:
                    times['finished']=perf_counter()
        try:
            return await original(measured_call)
        finally:
            # 取消后后台callback可能继续。只记此时已发生的边界，不虚填0，
            # 不在迟到callback里修改已经返回给消费者的观测。
            with lock:
                completed=dict(times)
            if 'started' in completed:
                observation.add('vdb_query_pool_wait_ms',max(0,completed['started']-submitted)*1000)
            if 'finished' in completed:
                observation.add('vdb_query_backend_ms',max(0,completed['finished']-completed['started'])*1000)
    return call


class SDKObservation:
    def __init__(self, *, sdk_version):
        self.installed=[]
        self.applied=False
        if sdk_version!='2.0.3': return
        from hy_memory.pipelines import registry,reader_base
        from hy_memory.core import embed_service
        from hy_memory.data import vector_store_chroma
        root=Path(embed_service.__file__).resolve().parents[1]
        for name,digest in SOURCES.items():
            path=root/name
            if (path.is_symlink() or not path.is_file()
                    or hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=digest):
                return
        targets=[(registry.ComponentFactory,'get_reader','reader_get_ms','pipelines/registry.py'),
            (reader_base,'lemmatize_for_bm25','tokenize_ms','pipelines/_retrieval/lemmatize.py'),
            (embed_service.EmbedService,'embed_with_meta','embed_rpc_ms','core/embed_service.py'),
            (embed_service.EmbedService,'_get_client','embed_client_get_ms','core/embed_service.py'),
            (vector_store_chroma,'_run_in_vdb_pool',None,'data/vector_store_chroma.py')]
        targets += [(vector_store_chroma.ChromaVectorStore,name,stage,'data/vector_store_chroma.py')
            for name,stage in (('search','vdb_query_ms'),('get_by_id','vdb_get_ms'),('list_by_user','vdb_list_ms'))]
        for owner,name,_,path in targets:
            original=getattr(owner,name,None)
            if (not inspect.isfunction(original) or hasattr(original,'__wrapped__')
                    or Path(original.__code__.co_filename).resolve()!=(root/path).resolve()):
                return
        try:
            for owner,name,stage,_ in targets:
                original=getattr(owner,name)
                wrapped=_wrap_vdb_pool(original) if stage is None else _wrap(original,stage)
                setattr(owner,name,wrapped)
                self.installed.append((owner,name,original,wrapped))
            self.applied=True
        except BaseException:
            self.close()
            raise

    def close(self):
        for owner,name,original,wrapped in reversed(self.installed):
            if getattr(owner,name) is not wrapped:
                raise RuntimeError('hy_sdk_observer_ownership_changed')
            setattr(owner,name,original)
        self.installed=[]
        self.applied=False

    def prepare_local_backends(self):
        """仅初始化已核验的本地依赖；不创建输入事件或调用任何SDK业务方法。"""
        if not self.applied:
            return {'prepared': False, 'import_ms': 0.0, 'segmenter_ms': 0.0}
        started = perf_counter()
        try:
            # 原首次向量请求会导入同一SDK依赖；导入不建立HTTP请求。
            # openai模块还会延迟导出客户端类；只解析公开类，不实例化或发请求。
            getattr(importlib.import_module('openai'), 'AsyncOpenAI')
            # 首次client.embeddings还会导入整个resources包及其Pydantic模型。
            # 提前解析同一公开资源类；不创建client/请求，不触碰SDK业务存储。
            getattr(importlib.import_module('openai.resources.embeddings'), 'AsyncEmbeddings')
            imported = perf_counter()
            from hy_memory.pipelines import reader_base
            # 固定本地中文分词函数，仅初始化jieba及其进程内LRU；无记忆存储入口。
            reader_base.lemmatize_for_bm25('初始化')
        except Exception:
            # 预备失败保持原首次调用的报错/降级，不放宽业务成功条件。
            return {'prepared': False, 'import_ms': 0.0, 'segmenter_ms': 0.0}
        return {'prepared': True, 'import_ms': round((imported-started)*1000,3),
                'segmenter_ms': round((perf_counter()-imported)*1000,3)}
