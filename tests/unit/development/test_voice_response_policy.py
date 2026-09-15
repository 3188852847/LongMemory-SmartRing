"""用合成消息验证语音策略隔离和真正的流式透传，不调用云端。"""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
from voice_response_policy import REALTIME_INSTRUCTION, STYLE_ENV, prepare_voice_dialogue
from voice_latency import _ObservedLLM


def test_policy_preserves_memory_tool_order_and_does_not_accumulate():
    dialogue = [
        {"role": "system", "content": "合成角色；记忆只作为证据。"},
        {"role": "user", "content": "合成记忆证据"},
        {"role": "assistant", "tool_calls": [{"id": "synthetic", "type": "function"}]},
        {"role": "tool", "tool_call_id": "synthetic", "content": "合成结果"},
        {"role": "user", "content": "请详细说明合成问题。"},
    ]
    original = deepcopy(dialogue)
    first = prepare_voice_dialogue(dialogue, style="realtime")
    second = prepare_voice_dialogue(dialogue, style="realtime")
    repeated = prepare_voice_dialogue(first, style="realtime")
    assert dialogue == original
    assert first == second == repeated
    assert first[0]["content"].startswith(original[0]["content"])
    assert first[0]["content"].count(REALTIME_INSTRUCTION) == 1
    assert first[1:] == original[1:]
    # 模拟上游 normalize_dialogue 的补写，不反向污染原工具调用消息。
    first[2]["content"] = ""
    assert dialogue == original


@pytest.mark.parametrize("dialogue", [[], [{"role": "user", "content": "合成问题"}]])
def test_missing_system_message_gets_one_without_changing_input(dialogue):
    original = deepcopy(dialogue)
    prepared = prepare_voice_dialogue(dialogue, style="realtime")
    assert prepared[0] == {"role": "system", "content": REALTIME_INSTRUCTION}
    assert prepared[1:] == original
    assert dialogue == original


def test_non_text_system_message_is_preserved():
    dialogue = [{"role": "system", "content": [{"type": "text", "text": "合成规则"}]}]
    prepared = prepare_voice_dialogue(dialogue, style="realtime")
    assert prepared[0]["content"] == REALTIME_INSTRUCTION
    assert prepared[1:] == dialogue


def test_original_environment_switch_restores_existing_request(monkeypatch):
    dialogue = [{"role": "user", "content": "合成问题"}]
    monkeypatch.setenv(STYLE_ENV, " original ")
    assert prepare_voice_dialogue(dialogue) is dialogue
    monkeypatch.delenv(STYLE_ENV)
    assert prepare_voice_dialogue(dialogue)[0]["content"] == REALTIME_INSTRUCTION


class Tracker:
    def __init__(self): self.events = []
    def bind_sentence(self): self.events.append("bind")
    def mark(self, field): self.events.append(field)
    def fail(self, code): self.events.append(code)


@pytest.mark.parametrize("method", ["response", "response_with_functions"])
@pytest.mark.parametrize("keyword_dialogue", [False, True])
def test_observer_applies_policy_and_preserves_incremental_output(method, keyword_dialogue, monkeypatch):
    monkeypatch.delenv(STYLE_ENV, raising=False)
    events = []
    captured = []

    class Provider:
        def response(self, session_id, dialogue, **kwargs):
            captured.append((session_id, dialogue, kwargs))
            events.append("first")
            yield "第一句。" if method == "response" else ("第一句。", None)
            events.append("second")
            yield "后一句。" if method == "response" else ("后一句。", None)
        response_with_functions = response

    tracker = Tracker()
    provider = Provider()
    wrapped = _ObservedLLM(SimpleNamespace(_longmemory_voice_latency=tracker), provider)
    dialogue = [{"role": "system", "content": "合成角色"}, {"role": "user", "content": "合成问题"}]
    original = deepcopy(dialogue)
    options = {"max_tokens": 512, "temperature": 0.4}
    if method == "response_with_functions":
        options["functions"] = [{"type": "function", "function": {"name": "synthetic"}}]
    if keyword_dialogue:
        output = getattr(wrapped, method)(session_id="synthetic-session", dialogue=dialogue, **options)
    else:
        output = getattr(wrapped, method)("synthetic-session", dialogue, **options)
    assert events == []
    first = next(output)
    assert first == ("第一句。" if method == "response" else ("第一句。", None))
    assert events == ["first"]  # 未收齐回答才交出首增量。
    assert len(list(output)) == 1
    assert captured[0][0] == "synthetic-session"
    assert captured[0][1][0]["content"].endswith(REALTIME_INSTRUCTION)
    assert captured[0][2] == options
    assert dialogue == original
    assert "llm_first_output_ms" in tracker.events


def test_observer_original_mode_does_not_modify_shared_provider_or_other_callers(monkeypatch):
    monkeypatch.setenv(STYLE_ENV, "original")
    captured = []

    class Provider:
        def response(self, session_id, dialogue, **kwargs):
            captured.append(dialogue)
            yield "合成结果。"

    provider = Provider()
    connection = SimpleNamespace(_longmemory_voice_latency=Tracker())
    wrapped = _ObservedLLM(connection, provider)
    dialogue = [{"role": "user", "content": "合成问题"}]
    list(wrapped.response("synthetic", dialogue))
    assert captured[-1] is dialogue
    monkeypatch.setenv(STYLE_ENV, "realtime")
    list(wrapped.response("synthetic", dialogue))
    assert captured[-1] is not dialogue
    list(provider.response("another-caller", dialogue))
    assert captured[-1] is dialogue


def test_model_failure_still_propagates_without_logging_response_content(monkeypatch):
    monkeypatch.delenv(STYLE_ENV, raising=False)

    class Provider:
        def response(self, *args, **kwargs):
            yield "合成首句。"
            raise TimeoutError("synthetic private response")

    tracker = Tracker()
    output = _ObservedLLM(SimpleNamespace(_longmemory_voice_latency=tracker), Provider()).response("synthetic", [])
    assert next(output) == "合成首句。"
    with pytest.raises(TimeoutError):
        next(output)
    assert tracker.events[-1] == "model_timeout"
    assert "private" not in repr(tracker.events)
