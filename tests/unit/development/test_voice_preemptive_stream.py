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
    def __init__(self, rows, *, status=200, gate=None):
        self.rows, self.status, self.gate = rows, status, gate
        self.content = self
        self.opened = self.closed = 0
        self.payload = None
        self.entered = asyncio.Event()

    @asynccontextmanager
    async def open(self, payload):
        self.payload = payload
        self.opened += 1
        self.entered.set()
        try:
            yield self
        finally:
            self.closed += 1

    async def __aiter__(self):
        if self.gate:
            await self.gate.wait()
        for line in self.rows:
            yield line


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
        assert c.budget.active == 0 and c.snapshot()["unknown_usage"] == 1
    asyncio.run(run())
