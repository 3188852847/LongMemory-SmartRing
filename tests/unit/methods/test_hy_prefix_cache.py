"""合成usage、确定性时钟与本地HTTP；不使用真实凭据或日用服务。"""

from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory import model_gateway as gateway_module
from longmemory.methods.hy_memory.model_gateway import ModelGateway
from longmemory.methods.hy_memory.prefix_cache import cache_evidence


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("af_cache_benchmark", ROOT / "scripts/development/models/benchmark_prefix_cache.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)
USAGE = {"prompt_tokens": 100, "completion_tokens": 3, "total_tokens": 103}


@pytest.mark.parametrize("usage,state,hit,miss", [
    (None, "unknown", None, None), ({}, "unknown", None, None),
    (USAGE, "unknown", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}, "reported_hit", 80, 20),
    ({**USAGE, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 100}, "reported_miss", 0, 100),
    ({**USAGE, "prompt_tokens_details": {"cached_tokens": 50}}, "reported_hit", 50, 50),
    ({**USAGE, "prompt_tokens_details": {"cached_tokens": 0}}, "reported_miss", 0, 100),
    ({**USAGE, "prompt_cache_hit_tokens": 80}, "invalid", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": True, "prompt_cache_miss_tokens": 99}, "invalid", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": -1, "prompt_cache_miss_tokens": 101}, "invalid", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": "80", "prompt_cache_miss_tokens": 20}, "invalid", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 21}, "invalid", None, None),
    ({**USAGE, "prompt_tokens_details": {"cached_tokens": 101}}, "invalid", None, None),
    ({**USAGE, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20,
      "prompt_tokens_details": {"cached_tokens": 70}}, "invalid", None, None),
])
def test_cache_evidence_never_interprets_absence_as_no_support(usage, state, hit, miss):
    original = deepcopy(usage)
    result = cache_evidence(usage, completed=True)
    assert (result["state"], result["hit_tokens"], result["miss_tokens"]) == (state, hit, miss)
    assert usage == original
    assert cache_evidence(usage, completed=False)["completed"] is False


def settings(url="https://synthetic-campus.invalid/v1"):
    return ModelSettings(provider="openai_compatible", model="DeepSeek-V4-Flash", base_url=url,
        api_key="synthetic-secret", max_tokens=32, allow_http=url.startswith("http:"), timeout_seconds=2)


def ledger(tmp_path):
    return FreeCampusCalls(tmp_path / "calls.sqlite3", proof={"request_model": "DeepSeek-V4-Flash"}, create=True)


@contextmanager
def events(payload):
    def lines():
        for packet in [
            {"choices": [{"delta": {"reasoning_content": "hidden", "content": "<thi"}}]},
            {"choices": [{"delta": {"content": "nk>hidden</think> "}}]},
            {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "hidden"}}]}}]},
            {"choices": [{"delta": {"content": "完成"}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
            {"choices": [], "usage": {**USAGE, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20}},
        ]:
            yield b"data: " + json.dumps(packet).encode() + b"\n"
            yield b"\n"
        yield b"data: [DONE]\n"; yield b"\n"
    yield 200, lines()


def test_gateway_times_only_filtered_effective_text_and_preserves_message_order(tmp_path, monkeypatch):
    ticks = iter([10., 10.125, 10.5])
    monkeypatch.setattr(gateway_module, "perf_counter", lambda: next(ticks))
    received = []
    @contextmanager
    def remote(payload):
        received.append(json.loads(payload))
        with events(payload) as response: yield response
    budget = ledger(tmp_path)
    server = ModelGateway(settings=settings(), budget=budget, encoder=object(), free_policy_verified=True, remote_stream=remote)
    body = bench.synthetic_body(settings().model, "synthetic")
    body["messages"][1:1] = [{"role": "user", "content": "合成旧问题"}, {"role": "assistant", "content": "合成旧答案"}]
    original = deepcopy(body)
    handler = bench.DiscardHandler()
    try:
        server.stream(body, handler)
        row = server.responses[0]
        assert row["model_ttft_ms"] == 125 and row["provider_elapsed_ms"] == 500
        assert row["cache"]["state"] == "reported_hit" and row["cache"]["completed"]
        assert row["finish_reason"] == "length" and handler.answer_matches()
        assert body == original and received[0]["messages"] == body["messages"]
        assert received[0]["thinking"] == {"type": "disabled"}
        assert budget.status()["unknown_or_inflight"] == 0
    finally: server.close()


def test_nonstream_does_not_claim_ttft(tmp_path):
    body = bench.synthetic_body(settings().model, "nonstream")
    body["stream"] = False
    server = ModelGateway(settings=settings(), budget=ledger(tmp_path), encoder=object(), free_policy_verified=True,
        remote=lambda payload: (200, json.dumps({"choices": [{"message": {"content": "完成"}}], "usage": USAGE}).encode()))
    try:
        assert server.complete("answer", body)[0] == 200
        assert server.responses[0]["model_ttft_ms"] is None
        assert server.responses[0]["cache"]["state"] == "unknown"
    finally: server.close()


@pytest.mark.parametrize("messages", [
    [{"role": "system", "content": "合成角色"}, {"role": "user", "content": '{"memory_evidence":"合成记忆"}'},
     {"role": "user", "content": "旧问"}, {"role": "assistant", "content": "旧答"}, {"role": "user", "content": "当前问题"}],
    [{"role": "system", "content": "合成角色\n当前时间为合成时间"}, {"role": "user", "content": "当前问题"},
     {"role": "assistant", "tool_calls": [{"id": "synthetic", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]},
     {"role": "tool", "tool_call_id": "synthetic", "content": "合成搜索结果"}],
    [{"role": "system", "content": [{"type": "text", "text": "结构化角色"}]}, {"role": "user", "content": "当前问题"}],
])
def test_observation_does_not_reorder_memory_time_history_or_tool_pairing(tmp_path, messages):
    received = []
    @contextmanager
    def remote(payload):
        received.append(json.loads(payload))
        with events(payload) as response: yield response
    server = ModelGateway(settings=settings(), budget=ledger(tmp_path), encoder=object(), free_policy_verified=True, remote_stream=remote)
    body = {**bench.synthetic_body(settings().model, "preserve"), "messages": deepcopy(messages)}
    try:
        server.stream(body, bench.DiscardHandler())
        assert body["messages"] == received[0]["messages"] == messages
    finally: server.close()


@contextmanager
def local_provider(*, missing_usage=False, only_reasoning=False, status=200):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.connection, body))
            cache = 0 if len(calls) % 3 == 1 else 80
            packets = [{"choices": [{"delta": {"reasoning_content": "SYNTHETIC_HIDDEN", "content": "<think>hidden</think>"}}]}]
            if not only_reasoning: packets.append({"choices": [{"delta": {"content": "完成。"}}]})
            packets.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            if not missing_usage:
                packets.append({"choices": [], "usage": {**USAGE, "prompt_cache_hit_tokens": cache,
                    "prompt_cache_miss_tokens": 100-cache, "arbitrary_secret": "must-not-save"}})
            raw = b"".join(b"data: " + json.dumps(p).encode() + b"\n\n" for p in packets) + b"data: [DONE]\n\n"
            self.send_response(status); self.send_header("Content-Length", str(len(raw))); self.end_headers()
            self.wfile.write(raw); self.wfile.flush()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    assert provider.server_port not in bench.DENIED_PORTS
    thread = Thread(target=lambda: provider.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try: yield settings(f"http://127.0.0.1:{provider.server_port}/v1"), calls
    finally: provider.shutdown(); provider.server_close(); thread.join(3)


def test_six_real_http_synthetic_requests_pair_payloads_and_connection_reuse(tmp_path):
    pauses = []
    with local_provider() as (model, calls):
        budget = ledger(tmp_path)
        nonces = iter(["a", "b"])
        rows = bench.run_pairs(model, budget, pause=pauses.append, nonce_factory=lambda: next(nonces))
    report = bench.summary(rows)
    assert len(calls) == budget.status()["attempt_count"] == report["actual_requests"] == 6
    assert report["support_evidence"] == "provider_reported_hit" and len(report["paired_deltas"]) == 2
    assert not report["p95_reported"] and not report["cache_causality_proven"]
    assert pauses == [2]*4
    for start in (0, 3):
        assert calls[start][0] is calls[start+1][0] and calls[start+2][0] is not calls[start][0]
        assert calls[start][1] == calls[start+1][1] == calls[start+2][1]
        assert rows[start]["payload_sha256"] == rows[start+2]["payload_sha256"]
    assert calls[0][1] != calls[3][1]
    assert all(call[1]["max_tokens"] == 32 and call[1]["thinking"] == {"type": "disabled"} for call in calls)
    assert all(row["has_effective_text"] and row["synthetic_answer_matches"] for row in rows)
    assert "must-not-save" not in json.dumps(rows) and "SYNTHETIC_HIDDEN" not in json.dumps(rows)


@pytest.mark.parametrize("mode", ["missing_usage", "error", "only_reasoning"])
def test_missing_usage_error_and_reasoning_only_do_not_fabricate_success(tmp_path, mode):
    with local_provider(missing_usage=mode=="missing_usage", only_reasoning=mode=="only_reasoning", status=400 if mode=="error" else 200) as (model, calls):
        budget = ledger(tmp_path)
        rows = bench.run_pairs(model, budget, pause=lambda value: None)
    report = bench.summary(rows)
    if mode == "only_reasoning":
        assert all(not row["has_effective_text"] for row in rows) and not report["paired_deltas"]
    else:
        assert len(calls) == len(rows) == 1  # 首次错误立即停止，绝不自动补样。
        assert report["support_evidence"] == "unconfirmed" and budget.status()["unknown_or_inflight"] == 1


@pytest.mark.parametrize("url,profile,model", [
    ("https://api.deepseek.com/v1", "campus", "DeepSeek-V4-Flash"),
    ("https://school.invalid/v1", "official", "DeepSeek-V4-Flash"),
    ("http://127.0.0.1:18770/v1", "campus", "DeepSeek-V4-Flash"),
    ("https://school.invalid:8003/v1", "campus", "DeepSeek-V4-Flash"),
    ("https://school.invalid/v1", "campus", "other"),
])
def test_live_guard_rejects_paid_loopback_daily_port_and_wrong_model(url, profile, model):
    with pytest.raises(ValueError, match="requires_selected_free_campus"):
        bench.validate_target(SimpleNamespace(base_url=url, model=model, api_key="synthetic"),
            {"profile": profile, "billing_policy": "owner_confirmed_free"})


def test_plan_only_does_not_read_credentials_or_access_network(monkeypatch, capsys):
    monkeypatch.setattr(bench, "selected_model", lambda *args: pytest.fail("must not read profiles"))
    assert bench.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["network_requests"] == 0 and report["maximum_calls"] == 6


def test_missing_free_policy_never_falls_back_to_unmetered_calls(tmp_path, monkeypatch):
    model = settings()
    monkeypatch.setattr(bench, "selected_model", lambda *args: (model, {"profile": "campus", "billing_policy": "owner_confirmed_free"}))
    def missing(*args): raise ValueError("campus_free_policy_required")
    monkeypatch.setattr(bench, "open_campus_calls", missing)
    monkeypatch.setattr(bench, "run_pairs", lambda *args: pytest.fail("must not send without policy"))
    monkeypatch.setattr(bench, "ROOT", tmp_path)
    output = tmp_path / "experiments/results"
    with pytest.raises(ValueError, match="campus_free_policy_required"):
        bench.main(["--execute-campus", "--owner-root", str(tmp_path), "--dispatch-id", "synthetic-dispatch", "--output", str(output)])
    assert not output.exists()
