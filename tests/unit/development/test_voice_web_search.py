import asyncio
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
import voice_web_config as config
import voice_web_search as web
import voice_waiting as waiting


def connection():
    conn = NS(sentence_id="turn", stop_event=threading.Event(), client_abort=False,
              sample_rate=16000, tts=NS(tts_audio_queue=__import__('queue').Queue()),
              _longmemory_voice_latency=NS(mark=lambda *a, **k: None))
    conn._longmemory_waiting = waiting.WaitingTurn(conn, "model", packets=(b'one', b'two'))
    return conn


def test_waiting_sentence_is_atomic_and_never_counts_as_answer(monkeypatch):
    import voice_latency
    dto = NS(SentenceType=NS(MIDDLE="middle"))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    c = connection()
    state = c._longmemory_waiting
    state.enqueue()
    assert c.tts.tts_audio_queue.qsize() == 1
    sentence_type, packets, text, sentence_id = c.tts.tts_audio_queue.get_nowait()
    assert len(packets) == 2 and all(isinstance(p, waiting.WaitingPacket) for p in packets)
    marks = []
    c._longmemory_voice_latency = NS(bind_sentence=lambda: None, mark=lambda *a, **k: marks.append(a))
    async def original(*a): pass
    sender = voice_latency.observed_audio_sender(original)
    asyncio.run(sender(c, sentence_type, packets, text, sentence_id))
    assert not marks
    asyncio.run(sender(c, sentence_type, waiting.AnswerPacket(b"answer", state), None, sentence_id))
    assert not marks  # 入流控队列不等于 socket 已发送。
    module = NS(_do_send_audio=original)
    waiting.install_waiting_sender(module)
    asyncio.run(module._do_send_audio(c, waiting.AnswerPacket(b"answer", state), {}))
    assert marks == [("first_audio_sent_ms",)]


def delta(arguments, name="web_search", ident="call-one", index=0):
    return NS(index=index, id=ident, function=NS(name=name, arguments=arguments))


def test_empty_model_output_cancels_late_waiting_cue():
    from voice_latency import _observe_generator
    c = connection()
    state = c._longmemory_waiting
    assert list(_observe_generator(c, iter(()), state)) == []
    state.enqueue()
    assert state.closed and c.tts.tts_audio_queue.empty()


class Provider:
    def __init__(self, chunks):
        self.chunks, self.calls, self.closed = chunks, [], False
    def response_with_functions(self, session_id, dialogue, **kwargs):
        self.calls.append(("decision", dialogue, kwargs))
        try:
            yield from self.chunks
        finally:
            self.closed = True
    def response(self, session_id, dialogue, **kwargs):
        self.calls.append(("answer", dialogue, kwargs))
        yield "来自可靠来源的回答。"


@pytest.mark.parametrize("provider", ["tavily", "metaso"])
def test_private_config_roundtrip_no_secret_repr_and_preserve_blank(tmp_path, provider):
    path = tmp_path / "local.env"
    assert config.load_config(path).provider == "disabled"
    config.save_config(path, provider=provider, api_key="synthetic-secret")
    assert "synthetic-secret" not in repr(config.load_config(path))
    config.save_config(path, provider=provider)
    assert config.load_config(path).api_key == "synthetic-secret"
    config.save_config(path, provider="disabled")
    assert config.load_config(path).api_key == ""


@pytest.mark.parametrize("raw", ["UNKNOWN=abc", "PROVIDER=tavily\nPROVIDER=metaso", "PROVIDER=other", "PROVIDER=tavily\nAPI_KEY=bad key"])
def test_invalid_config_never_overwritten(tmp_path, raw):
    path = tmp_path / "local.env"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        config.save_config(path, provider="tavily", api_key="synthetic-secret")
    assert path.read_text(encoding="utf-8") == raw


def test_search_preserves_sources_and_dates_drops_untrusted_fields():
    result = web.parse_results({"results": [{"title": "事实", "url": "https://example.org/a",
        "content": "摘要", "published_date": "2026-09-15", "raw_content": "private"}]}, "tavily", "day")
    assert result["time_filter_applied"]
    assert result["results"][0]["published_at"] == "2026-09-15"
    assert "private" not in json.dumps(result)
    assert web.parse_results({"results": []}, "tavily", "any")["status"] == "empty"


@pytest.mark.parametrize("url", ["file:///a", "https://user:pass@example.org", "javascript:alert(1)"])
def test_search_rejects_unsafe_links(url):
    assert not web.parse_results({"results": [{"title": "x", "content": "y", "url": url}]}, "tavily", "any")["results"]


def test_tools_one_search_no_memory_exfiltration_and_original_dialogue_intact(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig("tavily", "synthetic-key"))
    calls = []
    monkeypatch.setattr(web, "search_web", lambda c, args, **kw: calls.append(args.copy()) or {"status": "ok", "results": []})
    p = Provider([(None, [delta('{"query":"私人记忆里的地址","time_')]),
                  (None, [delta('range":"day"}', name="", ident="")])])
    original = [{"role": "system", "content": "私人记忆"},
                {"role": "user", "content": '{"speaker":"private-name","content":"今天的天气怎么样"}'}]
    baseline = json.dumps(original)
    conn = connection()
    assert list(web.web_response(conn, p, "s", original)) == ["来自可靠来源的回答。"]
    assert calls == [{"query": "今天的天气怎么样", "time_range": "day"}]
    assert json.dumps(original) == baseline
    assert [c[0] for c in p.calls] == ["decision", "answer"]
    assert len(p.calls[0][2]["functions"]) == 1
    assert p.closed and conn._longmemory_waiting.status == "query_ready"
    assert p.calls[1][1][-2]["role"] == "tool"


def test_normal_question_streams_without_search_or_second_model_call(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig("tavily", "synthetic-key"))
    monkeypatch.setattr(web, "search_web", lambda *a, **k: pytest.fail("no search"))
    p = Provider([("你好", None), ("呀", None)])
    assert list(web.web_response(connection(), p, "s", [])) == ["你好", "呀"]
    assert len(p.calls) == 1


def test_capability_question_uses_runtime_tool_fact_without_model_guessing(
    monkeypatch,
):
    monkeypatch.setattr(
        web, "load_config",
        lambda: config.SearchConfig("tavily", "synthetic-key"),
    )
    p = Provider([])
    answer = "".join(web.web_response(
        connection(), p, "s",
        [{"role": "user", "content": "你是否有联网功能？"}],
    ))
    assert "有" in answer and "只读网页搜索" in answer
    assert p.calls == []


def test_capability_question_reports_unavailable_without_configuration(
    monkeypatch,
):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig())
    p = Provider([])
    answer = "".join(web.web_response(
        connection(), p, "s",
        [{"role": "user", "content": "你可以联网搜索吗"}],
    ))
    assert "没有可用的联网搜索配置" in answer
    assert p.calls == []


def test_unconfigured_never_claims_to_search(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig())
    p = Provider([])
    list(web.web_response(connection(), p, "s", []))
    assert p.calls[0][0] == "answer" and "未配置联网" in p.calls[0][1][-1]["content"]


def test_search_failure_is_evidence_not_fabricated_success(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig("tavily", "synthetic-key"))
    def fail(*a, **k): raise RuntimeError("sensitive-url-and-key")
    monkeypatch.setattr(web, "search_web", fail)
    p = Provider([(None, [delta('{"query":"test","time_range":"any"}')])])
    c = connection()
    list(web.web_response(c, p, "s", [{"role": "user", "content": "查个公开事实"}]))
    assert c._longmemory_waiting.status == "query_failed"
    assert "sensitive" not in json.dumps(p.calls)
    assert "unavailable" in p.calls[1][1][-2]["content"]


def test_cancel_during_search_does_not_request_answer(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig("tavily", "synthetic-key"))
    c = connection()
    def fetch(*a, **k):
        c.sentence_id = "next-turn"
        return {"status": "ok"}
    monkeypatch.setattr(web, "search_web", fetch)
    p = Provider([(None, [delta('{"query":"test","time_range":"any"}')])])
    assert list(web.web_response(c, p, "s", [{"role": "user", "content": "公开问题"}])) == []
    assert len(p.calls) == 1


def test_multiple_or_unknown_tools_do_not_execute(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: config.SearchConfig("tavily", "synthetic-key"))
    monkeypatch.setattr(web, "search_web", lambda *a, **k: pytest.fail("must reject"))
    for d in (delta("{}", name="execute_shell"), delta("{}", index=1)):
        assert "不能核实" in "".join(web.web_response(connection(), Provider([(None, [d])]), "s", []))


def test_http_payload_uses_basic_three_results_and_fixed_https(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_bytes(self): yield b'{"results":[]}'
    class Client:
        def __init__(self, **kw):
            assert kw["follow_redirects"] is False
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def stream(self, *a, **kw):
            calls.append((a, kw))
            return Response()
    monkeypatch.setitem(sys.modules, "httpx", NS(Client=Client, Timeout=lambda *a, **k: None))
    result = web.search_web(config.SearchConfig("tavily", "synthetic-key"), {"query":"public", "time_range":"day"})
    assert result["status"] == "empty"
    assert calls[0][0] == ("POST", "https://api.tavily.com/search")
    payload = calls[0][1]["json"]
    assert payload == {"query":"public", "time_range":"day", "max_results":3,
                       "search_depth":"basic", "include_answer":False,
                       "include_raw_content":False, "auto_parameters":False}


def test_abort_rejects_all_remaining_cue_packets_and_new_turn_cannot_reuse():
    c = connection()
    state = c._longmemory_waiting
    c.client_abort = True
    async def original(*a): pytest.fail("must drop")
    module = NS(_do_send_audio=original)
    waiting.install_waiting_sender(module)
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"old", state), {}))
    c.client_abort = False
    c._longmemory_waiting = waiting.WaitingTurn(c, "model", packets=())
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"old", state), {}))


def test_actual_waiting_assets_are_bounded_and_identical_frame_durations(monkeypatch):
    monkeypatch.setattr(waiting, '_voice_context', lambda: {'identity':'f'*64, 'default':True})
    for kind in ("model", "web"):
        assert len(waiting.load_packets(kind, 16000)) == len(waiting.load_packets(kind, 24000))
        assert 1 <= len(waiting.load_packets(kind, 16000)) <= 35
    assert waiting.load_packets("model", 44100) == ()


def test_real_sender_separates_cue_answer_and_rejects_late_packets():
    c = connection()
    state = c._longmemory_waiting
    sent = []
    async def original(conn, packet, flow): sent.append(bytes(packet))
    module = NS(_do_send_audio=original)
    waiting.install_waiting_sender(module)
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"cue", state), {}))
    assert state.first_feedback_ms is not None and state.first_answer_ms is None
    waiting.mark_answer_ready(c)
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"cue-tail", state), {}))
    asyncio.run(module._do_send_audio(c, waiting.AnswerPacket(b"answer", state), {}))
    assert state.first_answer_ms is not None
    c.sentence_id = "next"
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"late", state), {}))
    asyncio.run(module._do_send_audio(c, waiting.AnswerPacket(b"old-answer", state), {}))
    # 真答案就绪后提示尾包立即作废；提示已开头也不能继续挡住有用回答。
    assert sent == [b"cue", b"answer"]


def test_answer_ready_before_cue_suppresses_cue():
    c = connection()
    state = c._longmemory_waiting
    waiting.mark_answer_ready(c)
    async def original(*a): pytest.fail("must not send")
    module = NS(_do_send_audio=original)
    waiting.install_waiting_sender(module)
    asyncio.run(module._do_send_audio(c, waiting.WaitingPacket(b"cue", state), {}))
    assert state.cue_state == "skipped" and state.first_feedback_ms is None


def test_feedback_protocol_rejects_private_fields_and_booleans():
    from longmemory.adapters.device_control.protocol import voice_feedback
    from longmemory.adapters.device_control.protocol import BridgeError
    value = connection()._longmemory_waiting.snapshot()
    assert voice_feedback(value) == value
    for extra in ({"text": "private"}, {"query_ms": True}, {"kind": []}):
        with pytest.raises(BridgeError):
            voice_feedback({**value, **extra})
