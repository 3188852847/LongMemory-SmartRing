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


def test_inflight_background_delays_formal_answer_but_queued_background_yields_and_candidate_cancels(tmp_path):
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
            first = executor.submit(model.complete, "hy", background, work_class="background")
            assert entered.wait(1)
            def next_background():
                queued.set()
                return model.complete("hy", background, work_class="background")
            second = executor.submit(next_background)
            assert queued.wait(1)
            timings["formal_submitted"] = perf_counter()
            answer = executor.submit(model.stream, body(), handler)
            async def queued_candidate():
                handle = model.open_candidate_response(body())
                pending = asyncio.create_task(consume(handle))
                try:
                    deadline = perf_counter()+1
                    while model._admission.snapshot()["waiting"]["answer"] != 1:
                        assert perf_counter() < deadline
                        await asyncio.sleep(.002)
                    deadline = perf_counter()+.16
                    while perf_counter() < deadline:
                        await asyncio.sleep(.002)
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
        assert calls == ["hy", "answer", "hy"]
        assert [row["admission_class"] for row in model.responses] == ["background", "answer", "background"]
        formal = next(row for row in model.responses if row["admission_class"] == "answer")
        assert formal["model_queue_ms"] >= 150 and formal["model_queue_by_active_ms"]["background"] >= 150
        report = {"controlled_background_hold_ms":160,
            "formal_wait_to_provider_ms":round((timings["formal_provider_entered"]-timings["formal_submitted"])*1000,3),
            "candidate_cancel_ms":round(timings["candidate_cancel_ms"],3),
            "provider_order":calls,"expected_priority_observed":True,"supplier":"controlled_function",
            "model_queue_ms":formal["model_queue_ms"],"model_ttft_ms":formal["model_ttft_ms"],
            "physical_playback":False,"school_requests":0}
        assert report["formal_wait_to_provider_ms"] >= 150
        (tmp_path/"gateway-contention.json").write_text(json.dumps(report),encoding="utf-8")
        print(json.dumps(report))
