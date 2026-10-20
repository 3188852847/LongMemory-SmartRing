"""真实共享网关/账本锁竞争；受控供应商替身，不访问学校或个人整理任务。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import sys
from threading import Event, Lock
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tests/unit/methods"))
from test_hy_candidate_response import gateway, complete_wire, body, consume, USAGE


def test_background_generation_holds_formal_answer_while_candidate_can_cancel_queued(tmp_path):
    entered, release, formal_entered, queued = Event(), Event(), Event(), Event()
    lock, calls, timings = Lock(), [], {}
    class Handler:
        def __init__(self): self.wfile = BytesIO()
        def send_response(self, _status): pass
        def send_header(self, *_args): pass
        def end_headers(self): pass
        def respond(self, *_args): raise AssertionError("formal generation failed")
    with gateway(tmp_path, []) as (model, ledger, received, _, __):
        def remote(payload):
            with lock:
                index = len(calls)
                calls.append("hy")
            if index == 0:
                entered.set()
                assert release.wait(3)
            return 200, json.dumps({"choices":[{"message":{"content":"合成后台结果"}}],"usage":USAGE}).encode()
        @contextmanager
        def stream(_payload):
            calls.append("answer")
            timings["formal_provider_entered"] = perf_counter()
            formal_entered.set()
            yield 200, complete_wire().splitlines(keepends=True)
        model._remote, model._remote_stream = remote, stream
        background = {"model":model.settings.model,"messages":[{"role":"system","content":"合成整理"}],
            "max_tokens":256,"stream":False}
        handler = Handler()
        with ThreadPoolExecutor(max_workers=3) as executor:
            first = executor.submit(model.complete, "hy", background)
            assert entered.wait(1)
            def next_background():
                queued.set()
                return model.complete("hy", background)
            second = executor.submit(next_background)
            assert queued.wait(1)
            timings["formal_submitted"] = perf_counter()
            answer = executor.submit(model.stream, body(), handler)
            async def queued_candidate():
                handle = model.open_candidate_response(body())
                pending = asyncio.create_task(consume(handle))
                try:
                    await asyncio.sleep(.16)
                    assert not formal_entered.is_set() and not answer.done() and not second.done()
                    assert ledger.status()["attempt_count"] == 1
                    began = perf_counter()
                    ack = await handle.cancel()
                    timings["candidate_cancel_ms"] = (perf_counter()-began)*1000
                    assert ack["owned_upstream_exited"] and not ack["provider_compute_stopped"]
                    pending.cancel()
                    try: await pending
                    except (asyncio.CancelledError, ValueError): pass
                finally:
                    release.set()
            try:
                asyncio.run(queued_candidate())
            finally:
                release.set()
            assert first.result(2)[0] == second.result(2)[0] == 200
            answer.result(2)
        assert b"[DONE]" in handler.wfile.getvalue()
        assert ledger.status()["attempt_count"] == 3 and ledger.status()["unknown_or_inflight"] == 0
        assert not received and not model._candidate_handles
        report = {"controlled_background_hold_ms":160,
            "formal_wait_to_provider_ms":round((timings["formal_provider_entered"]-timings["formal_submitted"])*1000,3),
            "candidate_cancel_ms":round(timings["candidate_cancel_ms"],3),
            "provider_order":calls,"priority_guaranteed":False,"supplier":"controlled_function",
            "physical_playback":False,"school_requests":0}
        assert report["formal_wait_to_provider_ms"] >= 150
        (tmp_path/"gateway-contention.json").write_text(json.dumps(report),encoding="utf-8")
        print(json.dumps(report))
