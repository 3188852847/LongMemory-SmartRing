import importlib.util
import json
from pathlib import Path
import sys
from copy import deepcopy

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
SPEC = importlib.util.spec_from_file_location("ae_voice_preemptive_input", SCRIPTS / "voice_preemptive_input.py")
v = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = v
SPEC.loader.exec_module(v)


QUERY = "合成当前问题"
ASR = {"content": QUERY, "language": "zh", "emotion": "NEUTRAL", "speaker": "合成说话人"}


def dialogue(**changes):
    actual = dict(ASR, **changes)
    return [{"role": "system", "content": "合成角色与记忆；时间/声纹均来自实际构造器"},
            {"role": "user", "content": "合成旧问题"},
            {"role": "assistant", "content": "合成旧回答"},
            {"role": "user", "content": json.dumps(actual, ensure_ascii=False)}]


def capture(messages, tools=False):
    return v.capture_effective_voice_input(QUERY, messages, tools_required=tools)


def test_actual_json_current_message_and_memory_query_are_separate_and_unchanged():
    messages = dialogue(event="SYNTHETIC_EVENT", unknown={"value": 1})
    before = deepcopy(messages)
    snapshot = capture(messages)
    assert snapshot.memory_query == QUERY
    assert snapshot.model_user_message == messages[-1]["content"]
    assert json.loads(snapshot.model_user_message)["speaker"] == ASR["speaker"]
    assert "SYNTHETIC_EVENT" in snapshot.model_user_message
    assert snapshot.messages == tuple((item["role"], item["content"]) for item in messages[:-1])
    assert snapshot.matches(capture(messages))
    assert messages == before
    assert QUERY not in repr(snapshot) and ASR["speaker"] not in repr(snapshot)


@pytest.mark.parametrize("key,value", [("language", "en"), ("emotion", "HAPPY"),
                                      ("speaker", "另一个合成说话人"), ("content", "合成修订问题")])
def test_current_message_metadata_or_content_change_cannot_match(key, value):
    original = capture(dialogue())
    assert not original.matches(capture(dialogue(**{key: value})))


@pytest.mark.parametrize("change", ["history", "date", "voiceprint", "style", "serialization", "query"])
def test_actual_history_system_serialization_and_memory_query_are_independent_gates(change):
    original = dialogue()
    changed = deepcopy(original)
    if change == "history":
        changed[1]["content"] += "（真实历史变化）"
    elif change in {"date", "voiceprint", "style"}:
        changed[0]["content"] += "实际" + change + "变化"
    elif change == "serialization":
        changed[-1]["content"] = json.dumps(ASR, ensure_ascii=False, separators=(",", ":"))
    else:
        snapshot = v.capture_effective_voice_input("不同记忆查询", changed, tools_required=False)
        assert not capture(original).matches(snapshot)
        return
    assert not capture(original).matches(capture(changed))


def test_available_tools_cannot_be_silently_removed_to_claim_match():
    original = dialogue()
    no_tools = capture(original)
    with_tools = capture(original, tools=True)
    assert not with_tools.eligible
    assert not with_tools.matches(with_tools) and not no_tools.matches(with_tools)
    assert with_tools.tools_required is True
    assert original == dialogue()


@pytest.mark.parametrize("item", [
    {"role": "user", "content": {"content": QUERY}},
    {"role": "user", "content": QUERY, "name": "synthetic-extra-metadata"},
    {"role": "tool", "content": "synthetic-tool"},
    {"role": "assistant", "content": None, "tool_calls": [{"id": "synthetic"}]},
])
def test_unsupported_effective_inputs_are_rejected_without_losing_fields(item):
    messages = dialogue()
    messages[-1] = item
    before = deepcopy(messages)
    assert capture(messages) is None
    assert messages == before


def test_snapshot_owns_immutable_text_copy_and_never_calls_input_builders():
    messages = dialogue()
    snapshot = capture(messages)
    messages[0]["content"] = "later system"
    messages[-1]["content"] = "later user"
    assert not snapshot.matches(capture(messages))
    assert snapshot.model_user_message == json.dumps(ASR, ensure_ascii=False)
    with pytest.raises(Exception):
        snapshot.model_user_message = QUERY


def test_current_user_counts_towards_original_32000_character_limit():
    messages = [{"role": "system", "content": "x" * 31990}, {"role": "user", "content": "y" * 11}]
    assert capture(messages) is None
    messages[-1]["content"] = "y" * 10
    assert capture(messages) is not None


def test_real_style_and_disabled_search_builders_preserve_raw_json_without_loading_configuration(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from voice_response_policy import prepare_voice_dialogue
    import voice_web_search as web
    monkeypatch.setattr(web, "load_config", lambda: pytest.fail("capture must not load private config"))
    source = dialogue()
    before = deepcopy(source)
    def actual_input():
        return web._with_system_instruction(prepare_voice_dialogue(source, style="realtime"), web._instruction(False))
    first, second = actual_input(), actual_input()
    assert capture(first).matches(capture(second))
    assert first[-1]["content"] == source[-1]["content"] and source == before


def test_configured_search_time_is_not_frozen_or_removed_to_make_match(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import time
    import voice_web_search as web
    first = web._with_system_instruction(dialogue(), web._instruction(True))
    time.sleep(.002)
    second = web._with_system_instruction(dialogue(), web._instruction(True))
    a, b = capture(first, tools=True), capture(second, tools=True)
    assert a.messages != b.messages and not a.matches(b)
    assert not a.eligible and not b.eligible
