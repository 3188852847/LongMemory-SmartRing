"""隔离探针仅包住原调用；合成时钟，无SDK实例、模型、数据库或网络。"""

import asyncio
import ast
from importlib import metadata
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
import hy_recall_stage_probe as probes


def test_known_sdk_tree_is_read_only_pinned_without_importing_sdk():
    site = ROOT / 'local/runtime/hy-memory/.venv/Lib/site-packages'
    if not (site/'hy_memory').is_dir():
        pytest.skip('existing isolated SDK source absent; no installation')
    distribution = next(d for d in metadata.distributions(path=[str(site)])
                        if d.metadata['Name'].replace('_','-') == 'hy-memory')
    probes.verify_sdk_tree(site/'hy_memory', distribution.version)
    targets = [('pipelines/registry.py','ComponentFactory','get_reader',True,'reader_name'),
        ('pipelines/_retrieval/lemmatize.py',None,'lemmatize_for_bm25',False,'text'),
        ('core/embed_service.py','EmbedService','embed_with_meta',True,'text'),
        ('data/vector_store_chroma.py','ChromaVectorStore','search',True,'query_embedding')]
    for name,cls,method,asynchronous,parameter in targets:
        node=ast.parse((site/'hy_memory'/name).read_text(encoding='utf-8'))
        if cls: node=next(n for n in node.body if isinstance(n,ast.ClassDef) and n.name==cls)
        function=next(n for n in node.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==method)
        assert isinstance(function,ast.AsyncFunctionDef)==asynchronous
        assert parameter in [p.arg for p in function.args.args+function.args.kwonlyargs]


def test_mismatched_version_sources_and_unisolated_use_fail_closed(tmp_path):
    with pytest.raises(ValueError,match='isolated_harness_required'): probes.HyRecallStageProbe()
    with pytest.raises(ValueError,match='version_mismatch'): probes.verify_sdk_tree(tmp_path,'2.0.4')
    with pytest.raises(ValueError,match='source_mismatch'): probes.verify_sdk_tree(tmp_path,'2.0.3')


def test_wrapping_reuses_one_existing_call_and_restores_every_reference(monkeypatch):
    now=[0.0];calls=[]
    probe=probes.HyRecallStageProbe(isolated=True,clock=lambda:now[0])
    class Reader:
        def __init__(self): self._readers={}
        async def get_reader(self,reader_name=''):
            calls.append('reader');now[0]+=.1
            self._readers.setdefault('legacy',object())
            return self._readers['legacy']
    async def embed(text): calls.append('embed');now[0]+=.2;return [[.1]],{'cache_hit':False}
    async def vector(query_embedding): calls.append('vector');now[0]+=.3;return ['private memory']
    def tokenize(text): calls.append('tokenize');now[0]+=.04;return 'private tokenized question'
    owners=[(Reader,'get_reader',True,'reader_get_ms'),(NS(call=tokenize),'call',False,'tokenize_ms'),
            (NS(call=embed),'call',True,'embed_rpc_ms'),(NS(call=vector),'call',True,'vdb_query_ms')]
    targets=[(owner,name,getattr(owner,name),asynchronous,stage) for owner,name,asynchronous,stage in owners]
    monkeypatch.setattr(probe,'_targets',lambda *args:targets)
    reader=Reader()
    async def execute():
        assert await reader.get_reader() is await reader.get_reader()
        assert owners[1][0].call('private question')=='private tokenized question'
        assert await owners[2][0].call('private question')==([[.1]],{'cache_hit':False})
        assert await owners[3][0].call([.1])==['private memory']
    with probe.install(None,None):
        with probe.scope('sdk_execute_ms','a'*32) as record:
            asyncio.run(execute())
        # 没有scope的调用不被计时，也不额外探测。
        previous=record['stages']['tokenize_ms'].copy()
        owners[1][0].call('private second question')
        assert record['stages']['tokenize_ms']==previous
        with pytest.raises(ValueError,match='already_installed'):
            with probe.install(None,None): pass
    assert all(getattr(owner,name) is original for owner,name,original,_,_ in targets)
    assert calls==['reader','reader','tokenize','embed','vector','tokenize']
    assert record['reader_creations']==1 and record['status']=='completed'
    assert record['stages']['sdk_execute_ms']['total_ms']==740
    assert record['stages']['reader_get_ms']=={'calls':2,'first_ms':100.0,'total_ms':200.0,'failed':0}
    assert record['stages']['embed_rpc_ms']['total_ms']==200
    assert record['stages']['vdb_query_ms']['total_ms']==300
    assert 'private' not in repr(record) and '.1' not in repr(record)


def test_exceptions_cancellation_and_new_scope_never_leak_old_round(monkeypatch):
    now=[0.0];probe=probes.HyRecallStageProbe(isolated=True,clock=lambda:now[0])
    error=RuntimeError('private body')
    def original(text): now[0]+=.1;raise error
    owner=NS(call=original)
    monkeypatch.setattr(probe,'_targets',lambda *a:[(owner,'call',original,False,'tokenize_ms')])
    with pytest.raises(RuntimeError) as caught:
        with probe.install(None,None):
            with probe.scope('sdk_execute_ms','a'*32) as old:
                owner.call('private')
    assert caught.value is error and owner.call is original
    assert old['status']=='failed' and old['stages']['tokenize_ms']['failed']==1
    with pytest.raises(asyncio.CancelledError):
        with probe.scope('sdk_execute_ms','b'*32) as cancelled:
            now[0]+=.2;raise asyncio.CancelledError()
    with probe.scope('sdk_roundtrip_ms','c'*32) as current:
        now[0]+=.3
        with pytest.raises(ValueError,match='already_active'):
            with probe.scope('sdk_execute_ms','d'*32): pass
    assert current['round_id']=='c'*32 and current['stages']['sdk_roundtrip_ms']['total_ms']==300
    assert current['stages']['tokenize_ms']['calls']==0
    assert cancelled['stages']['sdk_execute_ms']['total_ms']==200
    assert 'private' not in repr((old,cancelled,current))


def test_validation_is_atomic_before_patching_anything(monkeypatch):
    probe=probes.HyRecallStageProbe(isolated=True)
    def fail(*args): raise ValueError('hy_probe_binding_signature_mismatch')
    monkeypatch.setattr(probe,'_targets',fail)
    with pytest.raises(ValueError,match='signature_mismatch'):
        with probe.install(None,None): raise AssertionError('entered unvalidated probe')
    assert not probe._installed


def test_concurrent_reference_change_is_not_overwritten_and_harness_must_stop(monkeypatch):
    probe=probes.HyRecallStageProbe(isolated=True)
    original=lambda text:text
    replacement=lambda text:'another owner'
    owner=NS(call=original)
    monkeypatch.setattr(probe,'_targets',lambda *args:[(owner,'call',original,False,'tokenize_ms')])
    with pytest.raises(RuntimeError,match='concurrent_mutation_stop_harness'):
        with probe.install(None,None):
            owner.call=replacement
    assert owner.call is replacement and not probe._installed
