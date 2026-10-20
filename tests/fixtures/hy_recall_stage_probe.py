"""隔离 Hy 2.0.3 进程的内存探针；不导入 SDK、不发请求、不自动暖身。

父 harness 用 scope('sdk_roundtrip_ms') 包住既有一次 RPC；子隔离 worker 在
初始化后显式 install 已导入模块，用 scope('sdk_execute_ms') 包住原 execute。
仅在该 scope 内记内部阶段。两进程各算时长，不拼接绝对时间，不接生产 worker。
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
from importlib import metadata
import inspect
from pathlib import Path
import re
from time import perf_counter


SDK_VERSION = '2.0.3'
SOURCE_SHA256 = {
    'pipelines/registry.py': 'f0d1c45de64ebe181de62c4571fd87a788cfd9addab143300b32cdcf6d3e2850',
    'pipelines/reader_base.py': 'edbb334709b0c56007d8cd74197062d4c2f6e5084c0c4143517881988f4401f8',
    'pipelines/_retrieval/lemmatize.py': 'c7eee75fe45f8ddcc7d118f1532680c88cd9f5b3e9fe7f762caa1ddc729102da',
    'core/embed_service.py': '19a929f5a5c8b2d8c8266a594cc1c1be0ec5861e60b858ca5a380453096cf905',
    'data/vector_store_chroma.py': 'a3be99b273da02aa1ce860376886de76079e3c061400dc039c2408f69c4b1a33',
}
STAGES = ('sdk_roundtrip_ms', 'sdk_execute_ms', 'reader_get_ms', 'tokenize_ms', 'embed_rpc_ms', 'vdb_query_ms')


def verify_sdk_tree(root, version):
    """只读核验固定来源；版本/源码不同即拒绝，不猜兼容，不输出文件正文。"""
    if version != SDK_VERSION:
        raise ValueError('hy_probe_sdk_version_mismatch')
    root = Path(root).resolve()
    for name, digest in SOURCE_SHA256.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(
                path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != digest:
            raise ValueError('hy_probe_sdk_source_mismatch')


class HyRecallStageProbe:
    def __init__(self, *, isolated=False, clock=perf_counter):
        if isolated is not True:
            raise ValueError('hy_probe_isolated_harness_required')
        self.clock = clock
        self._current = ContextVar('hy_isolated_recall_probe', default=None)
        self._installed = False

    @contextmanager
    def scope(self, stage, round_id):
        if stage not in ('sdk_roundtrip_ms', 'sdk_execute_ms') or not isinstance(round_id, str) or not re.fullmatch(r'[0-9a-f]{32}', round_id):
            raise ValueError('hy_probe_scope_invalid')
        if self._current.get() is not None:
            raise ValueError('hy_probe_scope_already_active')
        record = {'version': 1, 'round_id': round_id, 'status': 'failed', 'reader_creations': 0,
                  'stages': {key: {'calls': 0, 'first_ms': None, 'total_ms': 0.0, 'failed': 0} for key in STAGES}}
        token = self._current.set(record)
        started = self.clock()
        try:
            yield record
            record['status'] = 'completed'
        finally:
            self._add(record, stage, started, record['status'] != 'completed')
            self._current.reset(token)

    def _add(self, record, stage, started, failed):
        item = record['stages'][stage]
        elapsed = round(max(0, self.clock() - started) * 1000, 3)
        item['calls'] += 1
        item['failed'] += int(failed)
        if item['first_ms'] is None:
            item['first_ms'] = elapsed
        item['total_ms'] = round(item['total_ms'] + elapsed, 3)

    def _targets(self, root, bindings):
        verify_sdk_tree(root, metadata.version('hy-memory'))
        specifications = (
            ('registry', 'pipelines/registry.py', 'ComponentFactory', 'get_reader', True, 'reader_get_ms', 'reader_name'),
            ('reader', 'pipelines/reader_base.py', None, 'lemmatize_for_bm25', False, 'tokenize_ms', 'text'),
            ('embed', 'core/embed_service.py', 'EmbedService', 'embed_with_meta', True, 'embed_rpc_ms', 'text'),
            ('vector', 'data/vector_store_chroma.py', 'ChromaVectorStore', 'search', True, 'vdb_query_ms', 'query_embedding'),
        )
        if set(bindings) != {row[0] for row in specifications}:
            raise ValueError('hy_probe_bindings_invalid')
        targets = []
        for key, name, cls, attr, asynchronous, stage, parameter in specifications:
            module = bindings[key]
            if Path(module.__file__).resolve() != (Path(root) / name).resolve():
                raise ValueError('hy_probe_binding_source_mismatch')
            owner = getattr(module, cls) if cls else module
            original = getattr(owner, attr)
            code_path = 'pipelines/_retrieval/lemmatize.py' if key == 'reader' else name
            if (not inspect.isfunction(original) or hasattr(original, '__wrapped__')
                    or Path(original.__code__.co_filename).resolve() != (Path(root) / code_path).resolve()
                    or inspect.iscoroutinefunction(original) != asynchronous
                    or parameter not in inspect.signature(original).parameters):
                raise ValueError('hy_probe_binding_signature_mismatch')
            targets.append((owner, attr, original, asynchronous, stage))
        return targets

    def _wrapper(self, original, asynchronous, stage):
        def reader_count(args):
            if stage != 'reader_get_ms' or not args:
                return 0
            return len(getattr(args[0], '_readers', {}))
        if asynchronous:
            @wraps(original)
            async def wrapped(*args, **kwargs):
                record = self._current.get()
                if record is None:
                    return await original(*args, **kwargs)
                before = reader_count(args); started = self.clock(); failed = True
                try:
                    result = await original(*args, **kwargs)
                    failed = False
                    if stage == 'reader_get_ms':
                        record['reader_creations'] += max(0, reader_count(args) - before)
                    return result
                finally:
                    self._add(record, stage, started, failed)
        else:
            @wraps(original)
            def wrapped(*args, **kwargs):
                record = self._current.get()
                if record is None:
                    return original(*args, **kwargs)
                started = self.clock(); failed = True
                try:
                    result = original(*args, **kwargs)
                    failed = False
                    return result
                finally:
                    self._add(record, stage, started, failed)
        return wrapped

    @contextmanager
    def install(self, sdk_root, bindings):
        if self._installed:
            raise ValueError('hy_probe_already_installed')
        targets = self._targets(sdk_root, bindings)  # 全部核验后才变更内存引用。
        installed = []
        try:
            self._installed = True
            for owner, attr, original, asynchronous, stage in targets:
                wrapped = self._wrapper(original, asynchronous, stage)
                setattr(owner, attr, wrapped)
                installed.append((owner, attr, original, wrapped))
            yield self
        finally:
            changed = False
            for owner, attr, original, wrapped in reversed(installed):
                if getattr(owner, attr) is wrapped:
                    setattr(owner, attr, original)
                else:
                    changed = True  # 不覆盖第三方并发改动；隔离进程须终止，不能继续采样。
            self._installed = False
            if changed:
                raise RuntimeError('hy_probe_concurrent_mutation_stop_harness')
