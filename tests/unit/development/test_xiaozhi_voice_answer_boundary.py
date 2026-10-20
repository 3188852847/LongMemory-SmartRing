"""Pinned native consumer evidence, not proof of the owner's unknown raw response format."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from xiaozhi_voice_boundary_driver import voice_text, wire, provider


@pytest.mark.parametrize('functions', [False, True])
def test_dedicated_reasoning_field_is_not_projected_to_shared_voice_text(functions):
    result = voice_text([wire(reasoning_content='synthetic-internal'), wire('合成回答。')], functions=functions)
    assert result['tts_input_text'] == result['stored_sentence_text'] == result['assistant_text'] == '合成回答。'
    assert result['completed'] and result['streams_closed']


def test_pinned_tool_branch_exposes_explicit_think_content_to_both_text_sinks():
    result = voice_text([wire('<think>synthetic-internal'), wire('</think>合成回答。')], functions=True)
    expected = '<think>synthetic-internal</think>合成回答。'
    assert result['tts_input_text'] == result['stored_sentence_text'] == result['assistant_text'] == expected


@pytest.mark.parametrize('functions', [False, True])
def test_pinned_fragmented_tag_exposes_internal_sentinel_in_both_branches(functions):
    result = voice_text([wire(text) for text in ('<thi', 'nk>', 'synthetic-internal', '</thi', 'nk>', '合成回答。')], functions=functions)
    assert result['tts_input_text'] == result['stored_sentence_text'] == result['assistant_text']
    assert 'synthetic-internal' in result['tts_input_text']
    assert result['streams_closed']


@pytest.mark.parametrize('functions', [False, True])
def test_normal_analysis_words_and_new_turn_do_not_reuse_previous_text(functions):
    first = voice_text([wire('上一轮合成文本。')], functions=functions)
    second = voice_text([wire('这里的 analysis 和 think 是普通词。')], functions=functions,
        connection=first['connection'])
    assert first['sentence_ids'].isdisjoint(second['sentence_ids'])
    assert second['tts_input_text'] == second['stored_sentence_text'] == second['assistant_text'] == '这里的 analysis 和 think 是普通词。'


def test_native_tool_deltas_remain_structured_and_stream_is_closed():
    tool = {'index': 0, 'id': 'synthetic-tool', 'type': 'function',
        'function': {'name': 'synthetic_tool', 'arguments': '{"value":"analysis"}'}}
    instance, streams, _ = provider([wire(tool_calls=[tool])])
    result = list(instance.response_with_functions('synthetic-session', [], functions=[]))
    assert result[0][0] == ''
    assert result[0][1][0].function.arguments == '{"value":"analysis"}'
    assert streams[0].closed
