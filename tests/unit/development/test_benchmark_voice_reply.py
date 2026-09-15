"""公开合成 SSE/配置替身，不访问模型、个人配置、记忆或 GPU。"""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
import benchmark_voice_reply as benchmark


def config():
    return benchmark.OfficialConfig("synthetic-key-never-export", "deepseek-v4-flash")


def event(content=None, *, finish=None, model="deepseek-flash", **extra):
    delta = {} if content is None else {"content": content}
    delta.update(extra)
    body = {"id": "must-not-export-response-id", "model": model,
            "choices": [{"delta": delta, "finish_reason": finish}]}
    return "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.time = 20.0
        self.requests = []
        self.closed = False

    def clock(self):
        return self.time

    @contextmanager
    def open(self, settings, body, deadline, clock):
        self.requests.append(body)
        try:
            def lines():
                for delay, text in self.events:
                    self.time += delay
                    yield from text.encode("utf-8").splitlines(keepends=True)
            yield lines()
        finally:
            self.closed = True


def measure(stream, style="baseline", **kwargs):
    return benchmark.measure_reply(config(), benchmark.CASES[0], style,
                                   open_lines=stream.open, clock=stream.clock, **kwargs)


def test_actual_segmenter_timing_and_privacy():
    stream = FakeStream([(0.1, event(" ")), (0.2, event("这是自然完整的第一句话，")),
                         (0.3, event("接着补充一点内容。")), (0.1, event(finish="stop")),
                         (0.02, "data: [DONE]\n\n")])
    captured = []
    result = measure(stream, text_consumer=lambda first, text: captured.append((first, text)))
    assert result["llm_first_output_ms"] == result["first_segment_ready_ms"] == 300
    assert result["response_completed_ms"] == 720
    assert result["first_segment_chars"] == len("这是自然完整的第一句话，")
    assert result["actual_model"] == "deepseek-flash"
    assert stream.closed
    assert captured[0][0] == "这是自然完整的第一句话，"
    exported = json.dumps(result, ensure_ascii=False)
    assert all(value not in exported for value in [config().api_key, "must-not-export-response-id",
                                                   "这是自然完整的第一句话", benchmark.CASES[0][1]])
    assert config().api_key not in repr(config())


def test_short_opening_waits_for_current_coalescing_rule():
    stream = FakeStream([(0.1, event("可以呀，")), (0.2, event("我们先把桌面上的东西分类整理，")),
                         (0.1, event(finish="stop")), (0, "data: [DONE]\n\n")])
    result = measure(stream)
    assert result["llm_first_output_ms"] == 100
    assert result["first_segment_ready_ms"] == 300
    assert result["first_segment_chars"] == len("可以呀，我们先把桌面上的东西分类整理，")


def test_short_complete_reply_releases_only_after_stream_ends():
    stream = FakeStream([(0.1, event("明白了。")), (0.2, event(finish="stop")),
                         (0.1, "data: [DONE]\n\n")])
    result = measure(stream)
    assert result["llm_first_output_ms"] == 100
    assert result["first_segment_ready_ms"] == result["response_completed_ms"] == 400


def test_both_styles_match_sampling_and_apply_real_policy():
    baseline = benchmark.request_body(config(), "公开问题", "baseline")
    realtime = benchmark.request_body(config(), "公开问题", "realtime")
    from voice_response_policy import REALTIME_INSTRUCTION
    assert REALTIME_INSTRUCTION in realtime["messages"][0]["content"]
    assert REALTIME_INSTRUCTION not in baseline["messages"][0]["content"]
    assert realtime["messages"][1] == baseline["messages"][1]
    for body in (baseline, realtime):
        assert body["thinking"] == {"type": "disabled"}
        assert body["max_tokens"] == 256
        assert "temperature" not in body
        assert set(body) == {"model", "messages", "stream", "max_tokens", "thinking"}


@pytest.mark.parametrize("temperature", [True, -0.1, 2.1, float("nan"), float("inf"), "0.7"])
def test_bad_temperature_rejected_before_request(temperature):
    with pytest.raises(benchmark.BenchmarkError, match="temperature_invalid"):
        benchmark.request_body(config(), "公开问题", "baseline", temperature=temperature)


@pytest.mark.parametrize("tail,code", [
    (event(finish="length") + "data: [DONE]\n\n", "response_not_completed"),
    (event(finish="stop"), "stream_incomplete"),
    ("data: [DONE]\n\n", "stream_incomplete"),
    ('data: {"error":{"message":"secret-provider-error"}}\n\n', "official_stream_rejected"),
    ("data: not-json\n\n", "stream_json_invalid"),
    (event(tool_calls=[{"secret": "secret"}]), "unexpected_tool_call"),
    (event("x" * 4097), "response_too_large"),
])
def test_failed_stream_stops_without_retry_or_export(tail, code):
    stream = FakeStream([(0.1, event("第一句已经产生了一些文字，")), (0.1, tail)])
    captured = []
    with pytest.raises(benchmark.BenchmarkError, match=code):
        measure(stream, text_consumer=lambda *items: captured.append(items))
    assert stream.closed and len(stream.requests) == 1
    assert captured == []


def test_reasoning_tokens_are_not_counted_as_first_visible_answer():
    stream = FakeStream([(0.1, event(reasoning_content="private-model-reasoning")),
                         (0.2, event("这是一条普通完整短句。")), (0.1, event(finish="stop")),
                         (0, "data: [DONE]\n\n")])
    assert measure(stream)["llm_first_output_ms"] == 300


def test_absolute_deadline_stops_keepalive_stream():
    stream = FakeStream([(1.1, ": keepalive\n\n"), (0, event("晚到"))])
    with pytest.raises(benchmark.BenchmarkError, match="request_timeout"):
        measure(stream, timeout_seconds=1)
    assert stream.closed and len(stream.requests) == 1


@pytest.fixture
def official_file(tmp_path, monkeypatch):
    path = tmp_path / ".env.deepseek.local"
    monkeypatch.setattr(benchmark, "OFFICIAL_ENV", path)
    def write(base="https://api.deepseek.com/v1", extra=""):
        path.write_text("LONGMEMORY_LLM_BASE_URL=" + base + "\n"
                        "LONGMEMORY_LLM_MODEL=deepseek-v4-flash\n"
                        "LONGMEMORY_LLM_API_KEY=synthetic-only\n" + extra, encoding="utf-8")
        return path
    return write


@pytest.mark.parametrize("base", ["https://api.deepseek.com", "https://api.deepseek.com/",
                                  "https://api.deepseek.com/v1", "https://api.deepseek.com/v1/"])
def test_official_config_allows_only_known_roots(official_file, base):
    assert benchmark.load_official_config(official_file(base)).path == "/v1/chat/completions"


@pytest.mark.parametrize("base", ["http://api.deepseek.com", "https://campus.invalid/v1",
    "https://api.deepseek.com.evil.invalid", "https://api.deepseek.com@evil.invalid",
    "https://api.deepseek.com:443", "https://api.deepseek.com/v1?key=secret",
    "https://api.deepseek.com/v1#secret", "https://api.deepseek.com/v1/chat/completions"])
def test_other_endpoints_and_ambiguous_urls_rejected(official_file, base):
    with pytest.raises(benchmark.BenchmarkError, match="official_endpoint_required"):
        benchmark.load_official_config(official_file(base))


def test_refuses_arbitrary_files_and_duplicate_keys(official_file, tmp_path):
    path = official_file(extra="LONGMEMORY_LLM_API_KEY=second-key\n")
    with pytest.raises(benchmark.BenchmarkError, match="official_config_ambiguous"):
        benchmark.load_official_config(path)
    with pytest.raises(benchmark.BenchmarkError, match="official_config_path_required"):
        benchmark.load_official_config(tmp_path / ".env")


def test_main_default_never_reads_config_or_network(monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "load_official_config", lambda *_: pytest.fail("must not load"))
    assert benchmark.main([]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "not_run"


def test_main_alternates_case_order_with_bounded_requests(monkeypatch, capsys):
    monkeypatch.setattr(benchmark, "load_official_config", lambda _: config())
    calls = []
    def measured(settings, case, style, **kwargs):
        calls.append((case[0], style, settings.model))
        return {"case": case[0], "style": style}
    monkeypatch.setattr(benchmark, "measure_reply", measured)
    assert benchmark.main(["--run-official", "--env-file", str(benchmark.OFFICIAL_ENV), "--repeat", "2"]) == 0
    assert [style for _, style, _ in calls] == ["baseline", "realtime", "realtime", "baseline",
                                                "realtime", "baseline", "baseline", "realtime"]
    assert len(json.loads(capsys.readouterr().out)["records"]) == 8


def test_transport_rejects_redirect_without_retry_and_never_reads_error(monkeypatch):
    instances = []
    class Response:
        status = 307
        def close(self): self.closed = True
        def readline(self, _): pytest.fail("never read rejection body")
    class Connection:
        def __init__(self, host, timeout):
            instances.append(self)
            assert host == "api.deepseek.com" and timeout <= 10
            self.sock = self
            self.response = Response()
        def connect(self): pass
        def settimeout(self, _): pass
        def request(self, method, path, **kwargs):
            assert method == "POST" and path == "/v1/chat/completions"
        def getresponse(self): return self.response
        def close(self): self.closed = True
    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    with pytest.raises(benchmark.BenchmarkError, match="official_http_rejected"):
        with benchmark.official_lines(config(), {}, 2, clock=lambda: 1):
            pytest.fail("redirect should not succeed")
    assert len(instances) == 1
    assert instances[0].closed and instances[0].response.closed


def test_main_sanitizes_unexpected_exceptions(monkeypatch, capsys):
    def bad(_): raise OSError("synthetic-key-never-export provider secret body")
    monkeypatch.setattr(benchmark, "load_official_config", bad)
    assert benchmark.main(["--run-official", "--env-file", "unused"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "benchmark_failed"}


def test_transport_phases_are_disjoint_and_first_text_still_includes_connect(monkeypatch):
    # 不用真实时钟等候：110 ms 建连，30 ms 写请求，200 ms 等响应头，
    # 然后再等 500 ms 首文本。首字合计 840 ms，不能误报成纯模型计算。
    timer = [20.0]
    connections = []
    wire = []
    for delay, text in [(0.5, event("这是一句完整的自然回答。")),
                        (0.1, event(finish="stop")), (0, "data: [DONE]\n\n")]:
        for index, line in enumerate(text.encode("utf-8").splitlines(keepends=True)):
            wire.append((delay if index == 0 else 0, line))

    class Response:
        status = 200
        def getheader(self, name, default):
            assert name == "Content-Type"
            return "text/event-stream; charset=utf-8"
        def readline(self, limit):
            assert limit == benchmark.MAX_LINE_BYTES + 1
            if not wire:
                return b""
            delay, value = wire.pop(0)
            timer[0] += delay
            return value
        def close(self): self.closed = True

    class Connection:
        def __init__(self, host, timeout):
            connections.append(self)
            assert host == "api.deepseek.com"
            self.sock = self
            self.response = Response()
        def connect(self): timer[0] += 0.11
        def settimeout(self, timeout): assert 0 < timeout <= 10
        def request(self, *args, **kwargs): timer[0] += 0.03
        def getresponse(self):
            timer[0] += 0.2
            return self.response
        def close(self): self.closed = True

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    result = benchmark.measure_reply(config(), benchmark.CASES[0], "baseline", clock=lambda: timer[0])
    assert result["connection_ms"] == 110
    assert result["headers_ms"] == 230
    assert result["first_output_after_headers_ms"] == 500
    assert result["llm_first_output_ms"] == 840
    assert result["response_completed_ms"] == 940
    assert len(connections) == 1
    assert connections[0].closed and connections[0].response.closed


def test_custom_stream_without_phase_observation_reports_unavailable_not_zero():
    stream = FakeStream([(0.1, event("这是一句完整的自然回答。")),
                         (0.1, event(finish="stop")), (0, "data: [DONE]\n\n")])
    result = measure(stream)
    assert result["connection_ms"] is result["headers_ms"] is result["first_output_after_headers_ms"] is None
