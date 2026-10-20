"""SDK观测包装与纯本地准备；使用替身模块，不导入真实SDK。"""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from longmemory.methods.hy_memory import sdk_observation as module
from longmemory.methods.hy_memory.observation import CURRENT, Observation


def test_unknown_sdk_version_does_not_import_or_patch():
    observation = module.SDKObservation(sdk_version='2.0.4')
    assert not observation.applied and observation.installed == []
    assert observation.prepare_local_backends() == {'prepared': False, 'import_ms': 0.0, 'segmenter_ms': 0.0}
    observation.close()


def test_local_preparation_resolves_public_class_and_segments_only_fixed_non_event_text(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): pytest.fail('must not construct a model client')
    class OpenAI:
        def __getattr__(self, name):
            calls.append(name)
            assert name == 'AsyncOpenAI'
            return Client
    monkeypatch.setattr(module.importlib, 'import_module', lambda name: OpenAI() if name == 'openai' else pytest.fail(name))
    pipelines = ModuleType('hy_memory.pipelines')
    pipelines.reader_base = SimpleNamespace(lemmatize_for_bm25=lambda text: calls.append(text))
    monkeypatch.setitem(sys.modules, 'hy_memory', ModuleType('hy_memory'))
    monkeypatch.setitem(sys.modules, 'hy_memory.pipelines', pipelines)
    times = iter((10, 10.4, 11))
    monkeypatch.setattr(module, 'perf_counter', lambda: next(times))
    observer = object.__new__(module.SDKObservation)
    observer.applied = True
    assert observer.prepare_local_backends() == {'prepared': True, 'import_ms': 400.0, 'segmenter_ms': 600.0}
    assert calls == ['AsyncOpenAI', '初始化']


def test_failed_local_preparation_has_fixed_diagnostics_and_no_business_success(monkeypatch):
    def unavailable(name): raise ImportError('private diagnostic detail')
    monkeypatch.setattr(module.importlib, 'import_module', unavailable)
    observer = object.__new__(module.SDKObservation)
    observer.applied = True
    assert observer.prepare_local_backends() == {'prepared': False, 'import_ms': 0.0, 'segmenter_ms': 0.0}


def test_sync_and_async_wrappers_preserve_single_call_result_and_inactive_behavior():
    calls, result = [], object()
    def sync(value): calls.append(value); return result
    async def asynchronous(value): calls.append(value); return result
    wrapped_sync = module._wrap(sync, 'vdb_get_ms')
    wrapped_async = module._wrap(asynchronous, 'vdb_query_ms')
    assert wrapped_sync('inactive') is result
    observation = Observation('a' * 32)
    with observation.activate():
        assert wrapped_sync('private-sync') is result
        assert asyncio.run(wrapped_async('private-async')) is result
    assert CURRENT.get() is None and calls == ['inactive', 'private-sync', 'private-async']
    assert observation.stages['vdb_get_ms']['calls'] == observation.stages['vdb_query_ms']['calls'] == 1
    assert 'private' not in repr(observation.snapshot())


def test_close_restores_owned_reference_and_rejects_replacement():
    original, wrapped, replacement = object(), object(), object()
    owner = SimpleNamespace(call=wrapped)
    observer = object.__new__(module.SDKObservation)
    observer.installed, observer.applied = [(owner, 'call', original, wrapped)], True
    observer.close()
    assert owner.call is original and not observer.applied
    observer.installed = [(owner, 'call', original, wrapped)]
    owner.call = replacement
    with pytest.raises(RuntimeError, match='ownership_changed'):
        observer.close()
    assert owner.call is replacement


def test_management_proof_binds_transitive_worker_wrappers(tmp_path, monkeypatch):
    from longmemory.methods.hy_memory import assembly
    names = ('worker.py', 'process_client.py', 'management_rpc.py', 'sdk_bridge.py',
             'short_embedding_input.py', 'sdk_observation.py', 'observation.py', 'layer_data.py', 'semantic.py', 'candidate_snapshot.py')
    for name in names:
        (tmp_path / name).write_bytes(b'synthetic\r\n')
    monkeypatch.setattr(assembly, '__file__', str(tmp_path / 'assembly.py'))
    original = assembly.management_primitives_identity()
    for name in names:
        (tmp_path / name).write_bytes(b'changed\n')
        assert assembly.management_primitives_identity() != original
        (tmp_path / name).write_bytes(b'synthetic\n')
        assert assembly.management_primitives_identity() == original
