"""摘要、并发归属与保留规则均使用合成日志。"""

import asyncio
import json
import logging
from pathlib import Path
import subprocess
import sys

from longmemory.infrastructure.logging.diagnostics import Diagnostics, REQUEST_CONTEXT, log_inventory
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
