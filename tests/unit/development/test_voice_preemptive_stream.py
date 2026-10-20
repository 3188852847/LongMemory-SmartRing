import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path

import pytest

from test_voice_preemptive import context, controller, p, stamp


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_preemptive_stream.py"
SPEC = importlib.util.spec_from_file_location("ae_voice_preemptive_stream", SCRIPT)
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)


def packet(text=None, *, delta=None, finish=None, usage=None):
    value = {"choices": [{"index": 0, "delta": delta if delta is not None else {"content": text},
                          "finish_reason": finish}]}
    if usage is not None:
        value["usage"] = usage
    return value


def lines(*packets, done=True):
    result = []
    for value in packets:
        result += [b"data: " + json.dumps(value, ensure_ascii=False).encode() + b"\n", b"\n"]
    if done:
        result += [b"data: [DONE]\n", b"\n"]
    return result


class Response:
    def __init__(self, rows, *, status=200, gate=None, header_gate=None, ack_gate=None, ack_error=False,
                 ack_override=None, close_error=False):
        self.rows, self.status, self.gate = rows, status, gate
        self.header_gate, self.ack_gate, self.ack_error = header_gate, ack_gate, ack_error
        self.ack_override = ack_override
        self.close_error = close_error
        self.content = self
        self.opened = self.closed = 0
        self.cancelled = 0
        self.upstream_closed = False
        self.payload = None
        self.entered = asyncio.Event()
        self.local_closed = asyncio.Event()

    def open(self, payload):
        self.payload = payload
        return Handle(self)

    async def __aiter__(self):
        if self.gate:
            await self.gate.wait()
        for line in self.rows:
            yield line


class Handle:
    request_id = "a" * 32

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        self.response.opened += 1
        self.response.entered.set()
        if self.response.header_gate:
            await self.response.header_gate.wait()
        return self.response

    async def __aexit__(self, *args):
        await self.aclose()

    async def cancel(self):
        self.response.cancelled += 1

    async def aclose(self):
        if not self.response.closed:
            self.response.closed += 1
            self.response.local_closed.set()
        if self.response.close_error:
            raise OSError("模拟关闭异常")

    async def wait_closed(self):
        if self.response.ack_gate:
            await self.response.ack_gate.wait()
        if self.response.ack_error:
            raise OSError("模拟上游关闭确认丢失")
        if self.response.ack_override is not None:
            return self.response.ack_override
        self.response.upstream_closed = True
        return {"request_id": self.request_id, "owned_upstream_exited": True,
                "provider_compute_stopped": False, "ledger_finalized": True, "usage_settled": True}


def model(response, verified=True):
    return s.GatewayPreparationModel(response.open, model="deepseek-v4-flash", campus_free_verified=verified)


def test_payload_order_final_content_reasoning_exclusion_and_no_tool_execution():
    async def run():
        response = Response(lines(
            packet(delta={"role": "assistant", "reasoning_content": "独立推理不可见"}),
            packet("<thi"), packet("nk>标签推理不可见</th"), packet("ink>合成回答。"),
            packet(finish="stop"),
            {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        ))
        c, ctx = controller(model(response)), context()
        assert c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        assert lease.claim(turn=stamp(), context=ctx) == "合成回答。"
        body = response.payload
        assert body["messages"][0] == {"role": "system", "content": ctx.messages[0][1]}
        assert body["messages"][-1] == {"role": "user", "content": "合成问题"}
        assert sum(row["role"] == "system" for row in body["messages"]) == 1
        assert "tools" not in body and body["tool_choice"] == "none"
        assert body["thinking"] == {"type": "disabled"} and body["n"] == 1
        assert body["max_tokens"] == 256
        assert c.snapshot()["observed_output_tokens"] == 5
        assert "不可见" not in repr(c.snapshot())
        assert response.opened == response.closed == 1
        assert await c.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("rows", [
    lines(packet(delta={"tool_calls": [{"id": "tool"}]}), packet(finish="stop")),
    lines(packet(delta={"function_call": {"name": "mutate"}}), packet(finish="stop")),
    lines(packet("片段"), packet(finish="length")),
    lines(packet("片段"), packet(finish="stop"), done=False),
    lines(packet("<think>未结束推理"), packet(finish="stop")),
    lines(packet("片段")),
    lines({"choices": [{"index": 1, "delta": {"content": "第二候选"}}]}),
    lines({"error": {"message": "敏感供应商错误"}}),
    [b"data: not json\n", b"\n"],
    [b"data: " + b"x" * 65536, b"\n"],
])
def test_bad_or_tool_streams_are_discarded_and_closed_without_retry(rows):
    async def run():
        response, ctx = Response(rows), context()
        c = controller(model(response))
        assert c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert response.opened == response.closed == 1
        assert c.snapshot()["failed"] == 1
        assert "敏感" not in repr(c.snapshot())
        assert await c.aclose()
    asyncio.run(run())


def test_http_error_and_free_policy_denial_close_or_skip():
    async def run():
        response, ctx = Response([], status=429), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert response.opened == response.closed == 1
        assert await c.aclose()
        response = Response([])
        c = controller(model(response, verified=False))
        assert not c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert response.opened == 0
        assert await c.aclose()
    asyncio.run(run())


def test_cancel_during_sse_read_closes_response_and_releases_slot():
    async def run():
        response, ctx = Response([], gate=asyncio.Event()), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await response.entered.wait()
        c.continued(turn_id=1, cancel_epoch=1)
        assert await c.aclose()
        assert response.opened == response.closed == 1
        assert response.upstream_closed
        assert c.budget.active == 0 and c.snapshot()["unknown_usage"] == 1
    asyncio.run(run())


def test_ready_and_budget_release_wait_for_upstream_ack_after_local_close():
    async def run():
        response, ctx = Response(lines(packet("完整合成回答"), packet(finish="stop")),
                                 ack_gate=asyncio.Event()), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await response.local_closed.wait()
        assert response.closed == 1 and not response.upstream_closed
        assert c.budget.active == 1 and c.snapshot()["ready"] == 0
        response.ack_gate.set()
        lease = await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx)
        assert lease.claim(turn=stamp(), context=ctx) == "完整合成回答"
        assert c.budget.active == 0 and response.upstream_closed
        assert await c.aclose()
    asyncio.run(run())


def test_cancel_before_headers_waits_for_owned_task_ack_and_holds_budget():
    async def run():
        response, ctx = Response([], header_gate=asyncio.Event(), ack_gate=asyncio.Event()), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        await response.entered.wait()
        c.continued(turn_id=1, cancel_epoch=1)
        await response.local_closed.wait()
        assert response.cancelled == 1 and response.closed == 1
        assert not response.upstream_closed and c.budget.active == 1
        assert not await c.aclose(timeout_seconds=0.01)
        response.ack_gate.set()
        assert await c.aclose()
        assert response.upstream_closed and c.budget.active == 0
    asyncio.run(run())


def test_failed_upstream_ack_keeps_budget_occupied_even_after_worker_exits():
    async def run():
        response, ctx = Response(lines(packet("合成回答"), packet(finish="stop")), ack_error=True), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert response.closed == 1 and not response.upstream_closed
        assert c.budget.active == 1
        assert c.snapshot()["cleanup_unconfirmed"] == 1
        assert c.snapshot()["unconfirmed_closes"] == 1
        assert not await c.aclose(timeout_seconds=0.01)
    asyncio.run(run())


def test_tool_first_output_never_counts_as_valid_answer_content():
    async def run():
        response, ctx = Response(lines(packet(delta={"content": "等一下", "tool_calls": [{"id": "tool"}]}),
                                       packet(finish="stop"))), context()
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=ctx)
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=ctx) is None
        assert c.snapshot()["observed_output_chars"] == 0 and c.snapshot()["hits"] == 0
        assert await c.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("receipt", [
    {"request_id": "b" * 32, "owned_upstream_exited": True,
     "ledger_finalized": True, "usage_settled": True},
    {"request_id": "a" * 32, "owned_upstream_exited": False,
     "ledger_finalized": True, "usage_settled": True},
    {"request_id": "a" * 32, "owned_upstream_exited": True,
     "ledger_finalized": False, "usage_settled": False},
])
def test_wrong_or_unconfirmed_request_ack_cannot_release_compute_slot(receipt):
    async def run():
        response = Response(lines(packet("合成回答"), packet(finish="stop")), ack_override=receipt)
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=context())
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=context()) is None
        assert c.budget.active == 1 and c.snapshot()["unconfirmed_closes"] == 1
        assert not await c.aclose()
    asyncio.run(run())


def test_close_exception_holds_slot_even_if_later_ack_object_reports_exit():
    async def run():
        response = Response(lines(packet("合成回答"), packet(finish="stop")), close_error=True)
        c = controller(model(response))
        c.provisional(turn=stamp(), transcript="合成问题", context=context())
        assert await c.confirmed(turn=stamp(), transcript="合成问题", context=context()) is None
        assert c.budget.active == 1 and c.snapshot()["unconfirmed_closes"] == 1
        assert not await c.aclose()
    asyncio.run(run())
