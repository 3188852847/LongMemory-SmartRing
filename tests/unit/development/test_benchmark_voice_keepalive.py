"""连接复用基准的合成验证；不调用真实 SDK 网络或读取私有配置。"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
import benchmark_voice_keepalive as benchmark
from benchmark_voice_reply import OfficialConfig, BenchmarkError


def config():
    return OfficialConfig("synthetic-only-secret", "deepseek-v4-flash")


def test_trace_keeps_only_counts_and_timing_and_never_reads_info():
    timer = [1.0]
    trace = benchmark.ConnectionTrace(lambda: timer[0])
    class ForbiddenInfo:
        def __getattribute__(self, _name): pytest.fail("trace must not inspect info")
    info = ForbiddenInfo()
    trace.trace("connection.connect_tcp.started", info)
    timer[0] += 0.12
    trace.trace("connection.connect_tcp.complete", info)
    trace.trace("proxy.start_tls.started", info)
    timer[0] += 0.2
    trace.trace("proxy.start_tls.complete", info)
    trace.trace("http11.receive_response_headers.started", info)
    timer[0] += 0.5
    trace.trace("http11.receive_response_headers.complete", info)
    trace.trace("http11.receive_response_body.started", info)
    result = trace.snapshot()
    assert result["connect_tcp_count"] == result["start_tls_count"] == 1
    assert result["connect_tcp_ms"] == 120
    assert result["start_tls_ms"] == 200
    assert result["receive_response_headers_ms"] == 500
    assert all(type(value) in {int, float} for value in result.values())
    trace.reset()
    assert all(value == 0 for value in trace.snapshot().values())


@pytest.mark.parametrize("host,scheme,path", [("evil.invalid", "https", "/v1/chat/completions"),
    ("api.deepseek.com", "http", "/v1/chat/completions"),
    ("api.deepseek.com", "https", "/other")])
def test_request_hook_blocks_other_destinations(host, scheme, path):
    trace = benchmark.ConnectionTrace()
    url = SimpleNamespace(host=host, scheme=scheme, path=path, port=None,
                          query=b"", username="", password="")
    with pytest.raises(BenchmarkError, match="official_endpoint_required"):
        trace.request_hook(SimpleNamespace(url=url, extensions={}))


@pytest.mark.parametrize("http2", [False, True])
def test_sdk_factory_preserves_proxy_defaults_and_changes_only_pool_expiry(monkeypatch, http2):
    calls = []
    defaults = SimpleNamespace(max_connections=1000, max_keepalive_connections=100, keepalive_expiry=5.0)
    def http_client(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(close=lambda: None)
    def sdk(**kwargs):
        calls.append(kwargs)
        return "fake-client"
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        DEFAULT_CONNECTION_LIMITS=defaults, DefaultHttpxClient=http_client,
        OpenAI=sdk, __version__="synthetic-sdk"))
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(
        Limits=lambda **kwargs: kwargs, Timeout=lambda *args, **kwargs: (args, kwargs),
        __version__="synthetic-httpx"))
    monkeypatch.setattr(benchmark.logging, "disable", lambda _: None)
    client, versions = benchmark.create_sdk_client(config(), 120.0, benchmark.ConnectionTrace(), http2=http2)
    assert client == "fake-client" and versions["openai"] == "synthetic-sdk"
    http, sdk_call = calls
    assert http["limits"] == {"max_connections": 1000, "max_keepalive_connections": 100,
                              "keepalive_expiry": 120.0}
    assert not {"trust_env", "proxy", "transport", "verify"}.intersection(http)
    assert http["follow_redirects"] is False
    assert http["http2"] is http2
    assert sdk_call["max_retries"] == 0
    assert sdk_call["base_url"] == "https://api.deepseek.com/v1"


def test_pair_plan_uses_same_client_after_idle_and_reverses_second_cycle():
    timer = [1.0]
    made = []
    measured = []
    def create(_config, expiry, _trace):
        item = SimpleNamespace(expiry=expiry, closed=False)
        item.close = lambda: setattr(item, "closed", True)
        made.append(item)
        return item, {"openai": "fake", "httpx": "fake"}
    def measure(client, *_args, **_kwargs):
        measured.append(client)
        timer[0] += 0.1
        return {"llm_first_output_ms": 100}
    def idle(seconds):
        assert seconds == 7
        timer[0] += seconds
    result = benchmark.run_comparison(config(), repeat=2, client_factory=create, measure=measure,
                                      clock=lambda: timer[0], sleeper=idle)
    assert [item.expiry for item in made] == [5, 120, 120, 5]
    assert len(measured) == 8 and all(item.closed for item in made)
    assert all(measured[index] is measured[index + 1] for index in (0, 2, 4, 6))
    assert [item["idle_seconds"] for item in result["records"]] == [0, 7, 0, 7, 0, 7, 0, 7]


def test_measure_keeps_text_and_response_id_out_of_result():
    timer = [10.0]
    calls = []
    class Stream:
        closed = False
        def __iter__(self):
            for content, reason in [("这是一句公开的合成回答。", None), (None, "stop")]:
                timer[0] += 0.2
                yield SimpleNamespace(id="do-not-export-id", model="deepseek-flash", choices=[
                    SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=reason)])
        def close(self): self.closed = True
    stream = Stream()
    def create(**kwargs):
        calls.append(kwargs)
        return stream
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = benchmark.measure_request(client, config(), benchmark.ConnectionTrace(lambda: timer[0]),
                                       clock=lambda: timer[0])
    assert result["llm_first_output_ms"] == 200 and result["response_completed_ms"] == 400
    assert result["response_chars"] == len("这是一句公开的合成回答。") and stream.closed
    assert all(item not in str(result) for item in ["这是一句", "do-not-export-id", config().api_key])
    assert calls[0]["max_tokens"] == 128 and "temperature" not in calls[0]
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_failed_request_aborts_plan_and_closes_client_without_retry():
    clients = []
    def create(*_args):
        client = SimpleNamespace(closed=False)
        client.close = lambda: setattr(client, "closed", True)
        clients.append(client)
        return client, {}
    def fail(*_args, **_kwargs): raise BenchmarkError("sdk_request_failed")
    with pytest.raises(BenchmarkError, match="sdk_request_failed"):
        benchmark.run_comparison(config(), client_factory=create, measure=fail,
                                  sleeper=lambda _: pytest.fail("must stop"))
    assert len(clients) == 1 and clients[0].closed


def test_default_command_does_not_read_config_or_import_sdk(monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "load_official_config", lambda _: pytest.fail("must not read"))
    monkeypatch.setattr(benchmark, "create_sdk_client", lambda *_: pytest.fail("must not create"))
    assert benchmark.main([]) == 0
    assert '"state":"not_run"' in capsys.readouterr().out


@pytest.mark.parametrize("version,connection,expected", [
    ("HTTP/2", "", False), ("HTTP/1.1", "keep-alive", False),
    ("HTTP/1.1", "Keep-Alive, Close", True), ("HTTP/1.0", "close", True),
])
def test_response_metadata_reports_actual_protocol_and_only_reads_connection_header(version, connection, expected):
    class Headers:
        def get(self, name, default):
            assert name == "connection"
            return connection
    response = SimpleNamespace(http_version=version, headers=Headers())
    result = benchmark.response_metadata(SimpleNamespace(response=response))
    assert result == {"response_http_version": version, "response_connection_close": expected}


def test_http2_opt_in_is_forwarded_to_each_pair_without_changing_request_count():
    received = []
    def create(*_args, **kwargs):
        received.append(kwargs)
        return SimpleNamespace(close=lambda: None), {}
    result = benchmark.run_comparison(config(), http2=True, client_factory=create,
                                      measure=lambda *_args, **_kwargs: {}, sleeper=lambda _: None)
    assert received == [{"http2": True}, {"http2": True}]
    assert result["http2_requested"] is True and len(result["records"]) == 4
