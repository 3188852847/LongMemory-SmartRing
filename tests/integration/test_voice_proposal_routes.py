"""真实内部鉴权与候选协议；宿主替身，无供应商/记忆或音频操作。"""

import asyncio
from copy import deepcopy
import socket

from aiohttp import ClientSession, web
import pytest

from longmemory.application.voice_proposal_contract import (
    ACTIONS, validate_voice_proposal_request, validate_voice_proposal_response,
)
from longmemory.entrypoints.api.routes.voice_proposals import register_voice_proposal_routes
from longmemory.entrypoints.api.security import Sessions, security_middleware


def request(action):
    base = {"version": 1, "connection_id": "a"*32, "turn_id": 7,
            "transcript_revision": 1, "cancel_epoch": 9}
    fields = {"snapshot": {"query": "合成问题", "session_id": "b"*32},
        "start": {"snapshot_id": "c"*32, "messages": [["system", "合成角色；记忆：合成事实"]], "tools_required": False},
        "confirm": {"snapshot_id": "c"*32, "query": "合成问题",
                    "messages": [["system", "合成角色；记忆：合成事实"]], "tools_required": False,
                    "formal_turn_id": "11111111-1111-4111-8111-111111111111", "client_round_id": "d"*32, "session_id": "b"*32},
        "cancel": {}, "close": {}}
    return {**base, **fields[action]}


def response(action):
    return {"snapshot": {"version": 1, "state": "ready", "snapshot_id": "c"*32,
                         "memory_context": "合成事实", "reason_code": None},
            "start": {"version": 1, "state": "preparing", "reason_code": None},
            "confirm": {"version": 1, "state": "adopted", "text": "合成回答", "reason_code": None},
            "cancel": {"version": 1, "state": "cancelled", "owned_upstream_exited": True, "provider_compute_stopped": False},
            "close": {"version": 1, "state": "closed", "owned_upstream_exited": True, "provider_compute_stopped": False}}[action]


@pytest.mark.parametrize("action", ACTIONS)
def test_frozen_five_requests_and_flat_responses(action):
    validate_voice_proposal_request(action, request(action))
    validate_voice_proposal_response(action, response(action))


@pytest.mark.parametrize("action", ["start", "confirm"])
def test_v2_actual_model_user_message_stays_distinct_from_memory_query_and_within_combined_limit(action):
    body = {**request(action), "input_protocol":2,
            "model_user_message":'{"content":"合成问题","language":"zh","emotion":"neutral","speaker":"合成说话人"}'}
    assert validate_voice_proposal_request(action, body) is body
    if action == "confirm": assert body["query"] == "合成问题"
    body["messages"] = [["system", "a"*16000]]
    body["model_user_message"] = "b"*16000
    validate_voice_proposal_request(action, body)
    body["messages"][0][1] += "c"
    with pytest.raises(ValueError, match="voice_proposal_request_invalid"):
        validate_voice_proposal_request(action, body)


@pytest.mark.parametrize("action", ["start", "confirm"])
@pytest.mark.parametrize("change", ["missing_protocol", "missing_message", "protocol_one", "protocol_bool",
                                    "protocol_three", "empty", "whitespace", "not_string", "invalid_utf8", "too_long"])
def test_v2_model_input_requires_exact_pair_and_never_silently_downgrades(action, change):
    body = {**request(action), "input_protocol":2,"model_user_message":"合成当前模型消息"}
    if change == "missing_protocol": body.pop("input_protocol")
    elif change == "missing_message": body.pop("model_user_message")
    elif change.startswith("protocol_"):
        body["input_protocol"] = {"protocol_one":1,"protocol_bool":True,"protocol_three":3}[change]
    else:
        body["model_user_message"] = {"empty":"","whitespace":" \n\t","not_string":{},"invalid_utf8":"\ud800","too_long":"x"*16001}[change]
    with pytest.raises(ValueError, match="voice_proposal_request_invalid"):
        validate_voice_proposal_request(action, body)


@pytest.mark.parametrize("action", ["snapshot", "cancel", "close"])
def test_v2_model_input_is_never_accepted_by_other_rpc_operations(action):
    with pytest.raises(ValueError, match="voice_proposal_request_invalid"):
        validate_voice_proposal_request(action,{**request(action),"input_protocol":2,"model_user_message":"合成正文"})


@pytest.mark.parametrize("action,field,value", [
    ("snapshot", "connection_id", "A"*32), ("snapshot", "query", ""),
    ("snapshot", "cancel_epoch", True), ("snapshot", "turn_id", 2**63),
    ("start", "messages", [["system", "one"], ["system", "two"]]),
    ("start", "messages", [[[], "invalid"]]), ("start", "messages", [["tool", "invalid"]]),
    ("start", "tools_required", "false"), ("confirm", "formal_turn_id", "invalid"),
    ("confirm", "transcript", "no-alias"), ("confirm", "query", "\ud800"),
])
def test_invalid_scope_extra_keys_or_side_effect_carriers_rejected(action, field, value):
    body = request(action)
    body[field] = value
    with pytest.raises(ValueError, match="voice_proposal_request_invalid"):
        validate_voice_proposal_request(action, body)


def test_close_ack_cannot_claim_provider_stopped_or_closing_as_complete():
    value = response("cancel")
    value["state"] = "closing"
    with pytest.raises(RuntimeError):
        validate_voice_proposal_response("cancel", value)
    value["owned_upstream_exited"] = False
    validate_voice_proposal_response("cancel", value)
    value["provider_compute_stopped"] = True
    with pytest.raises(RuntimeError):
        validate_voice_proposal_response("cancel", value)


def test_authenticated_real_http_dispatch_scope_budget_and_shutdown():
    class Host:
        def __init__(self): self.calls, self.closed, self.failure = [], 0, None
        def __getattr__(self, action):
            assert action in ACTIONS
            async def run(body):
                self.calls.append((action, deepcopy(body)))
                if self.failure:
                    raise self.failure
                return response(action)
            return run
        async def aclose(self):
            self.closed += 1
            return True
    host = Host()
    async def run():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        token = "e"*64
        app = web.Application(middlewares=[security_middleware(f"127.0.0.1:{port}", Sessions(), token)])
        register_voice_proposal_routes(app, host)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        base = f"http://127.0.0.1:{port}/api/internal/memory/proposals/"
        try:
            async with ClientSession() as client:
                async with client.post(base+"snapshot", json=request("snapshot")) as value:
                    assert value.status == 401
                assert not host.calls
                headers = {"Authorization": "Bearer "+token}
                for action in ACTIONS:
                    async with client.post(base+action, headers=headers, json=request(action)) as value:
                        assert value.status == 200 and await value.json() == response(action)
                for action in ("start","confirm"):
                    body = {**request(action),"input_protocol":2,
                            "model_user_message":'{"content":"合成问题","language":"zh"}'}
                    async with client.post(base+action, headers=headers, json=body) as value:
                        assert value.status == 200 and await value.json() == response(action)
                    assert host.calls[-1] == (action,body)
                before = len(host.calls)
                for body in ({**request("snapshot"), "source": "not-allowed"}, {**request("snapshot"), "query": "x"*200000}):
                    async with client.post(base+"snapshot", headers=headers, json=body) as value:
                        assert value.status == 400 and (await value.json())["error"] == "voice_proposal_request_invalid"
                assert len(host.calls) == before
                for body in ({**request("start"),"input_protocol":2},
                             {**request("start"),"model_user_message":"合成当前消息"},
                             {**request("start"),"input_protocol":1,"model_user_message":"合成当前消息"}):
                    async with client.post(base+"start",headers=headers,json=body) as value:
                        assert value.status == 400
                assert len(host.calls) == before
                for failure, status in ((ValueError("PRIVATE"), 409), (RuntimeError("PRIVATE"), 503)):
                    host.failure = failure
                    async with client.post(base+"start", headers=headers, json=request("start")) as value:
                        assert value.status == status and "PRIVATE" not in await value.text()
        finally:
            await runner.cleanup()
        assert host.closed == 1
    asyncio.run(run())
