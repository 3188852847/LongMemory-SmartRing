from contextlib import contextmanager
from io import BytesIO
import json
from threading import Event
from time import time
import http.client

import pytest

from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.budget import PricePolicy, SharedBudget
from longmemory.methods.hy_memory.model_gateway import ModelGateway


class Encoder: identity = "f" * 64


def packet(value): return b"data: " + json.dumps(value).encode() + b"\n"


class Handler:
    def __init__(self, writer=None): self.wfile = writer or BytesIO(); self.close_connection = False
    def send_response(self, status): self.status = status
    def send_header(self, *args): pass
    def end_headers(self): pass
    def respond(self, status, data): self.status = status


def gateway(tmp_path, stream):
    budget = SharedBudget(tmp_path / "budget.db", policy=PricePolicy(expires_at_unix=time()+3600), create=True)
    model = ModelSettings(provider="openai_compatible", base_url="https://api.deepseek.com",
                          api_key="synthetic-supplier-only", model="deepseek-v4-flash")
    return ModelGateway(settings=model, budget=budget, encoder=Encoder(), currency_verified=True, remote_stream=stream), budget


def body(): return {"model": "deepseek-v4-flash", "stream": True, "messages": [], "max_tokens": 512}


def test_real_http_stream_forwards_first_fragment_before_provider_finishes_and_settles(tmp_path):
    release, first = Event(), Event()
    @contextmanager
    def remote(payload):
        request = json.loads(payload)
        assert request["stream"] and request["stream_options"] == {"include_usage": True}
        assert request["thinking"] == {"type": "disabled"}
        assert "synthetic-supplier-only" not in payload.decode()
        def lines():
            yield packet({"choices": [{"delta": {"content": "合成首片"}}]}); yield b"\n"
            first.set()
            assert release.wait(3)
            yield packet({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}); yield b"\n"
            yield b"data: [DONE]\n"; yield b"\n"
        yield 200, lines()
    server, budget = gateway(tmp_path, remote)
    with server:
        connection = http.client.HTTPConnection("127.0.0.1", server.server.server_port, timeout=5)
        connection.request("POST", "/voice/v1/chat/completions", body=json.dumps(body()), headers={
            "Authorization": "Bearer " + server.token, "Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.readline()[5:])["choices"][0]["delta"]["content"] == "合成首片"
        assert first.wait(1) and not release.is_set()
        assert budget.report()["unknown_or_inflight"] == 1
        assert budget.report()["held_or_settled_upper_micro_cny"] == budget.policy.reservation
        release.set()
        assert b"[DONE]" in response.read()
        connection.close()
    assert budget.report()["unknown_or_inflight"] == 0
    assert budget.report()["held_or_settled_upper_micro_cny"] == 360


@pytest.mark.parametrize("failure", ["missing_usage", "missing_done", "provider_crash", "client_abort"])
def test_interrupted_stream_keeps_complete_reservation_without_retry(tmp_path, failure):
    calls = []
    @contextmanager
    def remote(payload):
        calls.append(payload)
        def lines():
            yield packet({"choices": [{"delta": {"content": "合成片段"}}]}); yield b"\n"
            if failure == "provider_crash": raise OSError("synthetic failure")
            if failure != "missing_usage":
                yield packet({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}); yield b"\n"
            if failure != "missing_done": yield b"data: [DONE]\n"; yield b"\n"
        yield 200, lines()
    class Abort(BytesIO):
        def write(self, data): raise BrokenPipeError()
    server, budget = gateway(tmp_path, remote)
    try:
        server.stream(body(), Handler(Abort() if failure == "client_abort" else None))
        assert len(calls) == 1
        assert budget.report()["unknown_or_inflight"] == 1
        assert budget.report()["held_or_settled_upper_micro_cny"] == budget.policy.reservation
    finally: server.close()
