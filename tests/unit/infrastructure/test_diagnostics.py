"""摘要、并发归属与保留规则均使用合成日志。"""

import asyncio
import json
import logging
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys

import pytest

from longmemory.infrastructure.logging.diagnostics import Diagnostics, REQUEST_CONTEXT, log_inventory, _comparison_path
from longmemory.infrastructure.logging import diagnostics as diagnostics_module
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging, log_event


def test_bounded_readonly_snapshot_and_conservative_outcomes():
    observer = Diagnostics(capacity=2)
    first = observer.begin("/secret?token=synthetic-secret")
    observer.finish(first, 200)
    second = observer.begin("device", mutating=True)
    observer.finish(second, 504, code="bridge_timeout")
    third = observer.begin("chat", mutating=True)
    observer.finish(third, 200)
    snapshot = observer.snapshot()
    assert len(snapshot["requests"]) == 2
    assert [row["outcome"] for row in snapshot["requests"]] == ["accepted", "unknown"]
    assert snapshot["device_playback"] == "unconfirmed"
    assert "secret" not in json.dumps(snapshot)
    snapshot["requests"][0]["code"] = "changed"
    assert observer.snapshot()["requests"][0]["code"] == "accepted"


def test_thread_context_links_memory_audit_to_server_request(tmp_path):
    path = tmp_path / "audit.jsonl"
    handler = configure_file_logging(path)
    observer = Diagnostics()
    trace = observer.begin("chat", mutating=True)

    async def run():
        token = REQUEST_CONTEXT.set((observer, trace[0]))
        try:
            await asyncio.to_thread(log_event, "memory_retrieved", turn_id="synthetic-turn", count=0)
            await asyncio.to_thread(log_event, "context_built", turn_id="synthetic-turn", count=0)
        finally:
            REQUEST_CONTEXT.reset(token)

    try:
        asyncio.run(run())
    finally:
        close_file_logging(handler)
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    assert all(row["request_id"] == trace[0] for row in rows)
    assert observer.snapshot()["requests"][0]["stage"] == "context"
    snapshot = observer.snapshot()
    snapshot["requests"][0]["stages"][0]["event"] = "changed"
    assert observer.snapshot()["requests"][0]["stages"][0]["event"] == "memory_retrieved"
    assert REQUEST_CONTEXT.get() is None


def test_process_owned_diagnostic_files_and_rotation(tmp_path):
    observer = Diagnostics(tmp_path)
    handler = observer.handler
    handler.maxBytes = 300
    try:
        for _ in range(30):
            observer.finish(observer.begin("device", mutating=True), 504, code="bridge_timeout")
        files = list((tmp_path / "data/logs/diagnostics").glob("*"))
        assert len(files) == 3
        assert all(file.stat().st_size <= 600 for file in files)
        assert all("synthetic-secret" not in file.read_text(encoding="utf-8") for file in files)
        other = Diagnostics(tmp_path)
        try:
            assert other.handler.baseFilename != handler.baseFilename
        finally:
            other.close()
    finally:
        observer.close()


def test_inventory_never_opens_log_body(tmp_path, monkeypatch):
    path = tmp_path / "data/logs/xiaozhi-demo-v1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("synthetic-private-conversation", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("body read")))
    rows = log_inventory(tmp_path)
    assert rows[1]["state"] == "present"
    assert rows[1]["bytes"] == path.stat().st_size
    assert "conversation" not in json.dumps(rows)
    assert str(tmp_path) not in json.dumps(rows)


def test_write_failure_does_not_break_control(tmp_path, monkeypatch):
    observer = Diagnostics(tmp_path)
    monkeypatch.setattr(observer.handler, "shouldRollover", lambda _: (_ for _ in ()).throw(OSError("synthetic-secret")))
    observer.finish(observer.begin("device"), 503)
    assert observer.snapshot()["persistence"] == "unavailable"
    observer.close()


def test_voice_persistence_failure_keeps_safe_memory_summary(tmp_path, monkeypatch):
    observer = Diagnostics(tmp_path)
    monkeypatch.setattr(observer.handler, "shouldRollover", lambda _: (_ for _ in ()).throw(OSError("private-secret")))
    try:
        observer.voice_event({"round_id": "a" * 24, "event": "memory_timeout", "sequence": 1})
        snapshot = observer.snapshot()
        assert snapshot["persistence"] == "unavailable"
        assert snapshot["voice"]["rounds"][0]["state"] == "failure_observed"
        assert "private" not in json.dumps(snapshot)
    finally:
        observer.close()


def test_real_separate_processes_write_distinct_files(tmp_path):
    # 子进程只加载工作树源码、写合成目录，不调用服务或联网。
    source = Path(__file__).resolve().parents[3] / "src"
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from longmemory.infrastructure.logging.diagnostics import Diagnostics
observer = Diagnostics(Path(sys.argv[2]))
observer.finish(observer.begin('memory_runtime', mutating=True), 500)
observer.close()
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(source), str(tmp_path)],
                                 cwd=source.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr.decode()
    files = list((tmp_path / "data/logs/diagnostics").glob("*.jsonl"))
    assert len(files) == 2
    assert all(json.loads(file.read_text(encoding="utf-8"))["outcome"] == "unknown" for file in files)


@pytest.mark.skipif(os.name!='nt',reason='Windows extended path representation')
@pytest.mark.parametrize('prefixed_check',[1,2])
def test_resolved_extended_drive_alias_does_not_disable_persistence(tmp_path,monkeypatch,prefixed_check):
    # 复现两个进程创建父目录时，ntpath.realpath可保留的等价扩展前缀。
    # 第一/第二次归属检查都必须继续执行，不能通过删掉检查修复。
    original=Path.resolve;checks=[]
    def resolve(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if path.suffix=='.jsonl' and path.parent.name=='diagnostics':
            checks.append(1)
            if len(checks)==prefixed_check and not str(result).startswith('\\\\?\\'):
                return Path('\\\\?\\'+str(result))
        return result
    monkeypatch.setattr(Path,'resolve',resolve)
    observer=Diagnostics(tmp_path)
    try:
        observer.finish(observer.begin('memory_runtime',mutating=True),500)
        assert observer.snapshot()['persistence']=='enabled'
    finally:observer.close()
    assert len(checks)==2
    files=list((tmp_path/'data/logs/diagnostics').glob('*.jsonl'))
    assert len(files)==1 and json.loads(files[0].read_text(encoding='utf-8'))['outcome']=='unknown'


@pytest.mark.parametrize('root,path,inside',[
    (r'D:\synthetic-root',r'\\?\D:\synthetic-root\data\log.jsonl',True),
    (r'\\?\D:\synthetic-root',r'd:\SYNTHETIC-ROOT\data\log.jsonl',True),
    (r'\\server\share\root',r'\\?\UNC\server\share\root\log.jsonl',True),
    (r'\\?\unc\server\share\root',r'\\SERVER\SHARE\root\log.jsonl',True),
    (r'D:\synthetic-root',r'\\?\D:\synthetic-root-other\log.jsonl',False),
    (r'D:\synthetic-root',r'\\?\E:\synthetic-root\log.jsonl',False),
    (r'\\server\share\root',r'\\?\UNC\other\share\root\log.jsonl',False),
    (r'\\server\share\root',r'\\?\UNC\server\other\root\log.jsonl',False),
    (r'D:\synthetic-root',r'\\?\GLOBALROOT\Device\synthetic-root\log.jsonl',False),
    (r'D:\synthetic-root',r'\\.\D:\synthetic-root\log.jsonl',False),
])
def test_extended_prefix_equivalence_keeps_drive_share_and_root_boundary(root,path,inside):
    assert _comparison_path(PureWindowsPath(path)).is_relative_to(
        _comparison_path(PureWindowsPath(root))) is inside


@pytest.mark.parametrize('path',[
    r'\\?\UNC\server',r'\\?\UNC\server'+chr(92),r'\\?\UNC\.\share\x',
    r'\\?\UNC\server\..\x',r'\\?\UNC\server?\share\x',
    r'\\?\GLOBALROOT\Device\synthetic',r'\\?\Volume{synthetic}\x',r'\\.\D:\x',
])
def test_malformed_unc_and_other_device_namespaces_are_not_rewritten(path):
    original=PureWindowsPath(path)
    assert _comparison_path(original)==original


@pytest.mark.parametrize('escape_check',[1,2])
def test_resolved_escape_is_still_refused_before_or_after_mkdir(tmp_path,monkeypatch,escape_check):
    original=Path.resolve;checks=[]
    outside=original(tmp_path.parent/'outside-synthetic'/'log.jsonl')
    def resolve(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if path.suffix=='.jsonl' and path.parent.name=='diagnostics':
            checks.append(1)
            if len(checks)==escape_check:return outside
        return result
    monkeypatch.setattr(Path,'resolve',resolve)
    observer=Diagnostics(tmp_path)
    try:
        observer.finish(observer.begin('memory_runtime',mutating=True),500)
        assert observer.snapshot()['persistence']=='unavailable' and observer.handler is None
    finally:observer.close()
    assert len(checks)==escape_check
    assert not list((tmp_path/'data/logs/diagnostics').glob('*.jsonl'))
    assert not outside.exists()


@pytest.mark.parametrize('failure_stage',['resolve','mkdir','handler_open'])
def test_initialization_io_failure_is_fail_open_without_private_details(tmp_path,monkeypatch,capsys,failure_stage):
    error=PermissionError('synthetic-private-path-and-body')
    def fail(*args,**kwargs):raise error
    if failure_stage=='resolve':
        original=Path.resolve
        def resolve(path,*args,**kwargs):
            if path.suffix=='.jsonl' and path.parent.name=='diagnostics':raise error
            return original(path,*args,**kwargs)
        monkeypatch.setattr(Path,'resolve',resolve)
    elif failure_stage=='mkdir':monkeypatch.setattr(Path,'mkdir',fail)
    else:monkeypatch.setattr(diagnostics_module,'SafeRotatingHandler',fail)
    observer=Diagnostics(tmp_path)
    try:
        observer.finish(observer.begin('memory_runtime',mutating=True),500)
        snapshot=observer.snapshot()
        assert snapshot['persistence']=='unavailable' and observer.handler is None
        assert snapshot['requests'][0]['outcome']=='unknown'
        assert 'synthetic-private' not in json.dumps(snapshot) and str(tmp_path) not in json.dumps(snapshot)
    finally:observer.close()
    output=capsys.readouterr()
    assert output.out==output.err==''


@pytest.mark.parametrize('kind',['symlink','junction'])
def test_real_directory_link_outside_root_is_refused(tmp_path,kind):
    if kind=='junction' and os.name!='nt':pytest.skip('Windows junction')
    root=tmp_path/'root';root.mkdir()
    target=tmp_path/'outside-root';target.mkdir()
    marker=target/'protected.txt';marker.write_text('synthetic-protected',encoding='utf-8')
    link=root/'data/logs/diagnostics';link.parent.mkdir(parents=True)
    if kind=='symlink':
        try:link.symlink_to(target,target_is_directory=True)
        except OSError as error:
            if getattr(error,'winerror',None)==1314:pytest.skip('directory symlink privilege unavailable')
            raise
    else:
        result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],
            capture_output=True,timeout=5)
        assert result.returncode==0,'synthetic junction creation failed'
    observer=Diagnostics(root)
    try:
        observer.finish(observer.begin('memory_runtime',mutating=True),500)
        assert observer.snapshot()['persistence']=='unavailable' and observer.handler is None
    finally:observer.close()
    assert list(target.iterdir())==[marker] and marker.read_text(encoding='utf-8')=='synthetic-protected'


def test_root_logger_unchanged(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    observer = Diagnostics(tmp_path)
    observer.finish(observer.begin("console"), 200)
    observer.close()
    assert root.handlers == before


def test_stages_are_bounded_and_late_evicted_context_is_harmless():
    observer = Diagnostics(capacity=1)
    first = observer.begin("chat")
    for _ in range(30):
        observer.stage(first[0], "memory_write")
    assert len(observer.snapshot()["requests"][0]["stages"]) == 16
    second = observer.begin("device")
    observer.stage(first[0], "answer_failed")
    observer.finish(first, 500)
    assert observer.snapshot()["requests"][0]["request_id"] == second[0]
    assert len(observer.started) == 1


def test_concurrent_worker_contexts_do_not_mix_request_ids(tmp_path):
    handler = configure_file_logging(tmp_path / "audit.jsonl")
    observer = Diagnostics()

    async def run_one(event):
        trace = observer.begin("chat")
        token = REQUEST_CONTEXT.set((observer, trace[0]))
        try:
            await asyncio.to_thread(log_event, event, turn_id="synthetic-turn", count=0)
            observer.finish(trace, 200)
            return trace[0]
        finally:
            REQUEST_CONTEXT.reset(token)

    async def run():
        return await asyncio.gather(run_one("memory_retrieved"), run_one("context_built"))

    try:
        retrieval_id, context_id = asyncio.run(run())
    finally:
        close_file_logging(handler)
    rows = {row["request_id"]: row for row in observer.snapshot()["requests"]}
    assert rows[retrieval_id]["stage"] == "retrieval"
    assert rows[context_id]["stage"] == "context"
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["event"]: row["request_id"] for row in audit} == {
        "memory_retrieved": retrieval_id, "context_built": context_id,
    }


def test_inventory_does_not_treat_directory_as_log(tmp_path):
    (tmp_path / "data/logs/launcher-events.jsonl").mkdir(parents=True)
    assert log_inventory(tmp_path)[0]["state"] == "not_a_file"
