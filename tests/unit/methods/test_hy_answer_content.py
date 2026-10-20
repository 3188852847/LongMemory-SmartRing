"""合成答案协议验证；不使用个人数据、供应商、GPU或SDK工作区。"""

from contextlib import contextmanager
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
from longmemory.infrastructure.config.settings import ModelSettings
from longmemory.methods.hy_memory.answer_content import FinalContent, FinalStream, final_response
from longmemory.methods.hy_memory.model_gateway import ModelGateway


TEXT = '<think>SYNTHETIC_REASONING</think>合成最终答案'
USAGE = {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}


@pytest.mark.parametrize('split', range(len(TEXT) + 1))
def test_explicit_leading_reasoning_is_hidden_across_every_content_split(split):
    parser = FinalContent()
    assert parser.feed(TEXT[:split]) + parser.feed(TEXT[split:]) + parser.finish() == '合成最终答案'


@pytest.mark.parametrize('text', ['普通答案', '标签示例：<think>正文</think>', '```\n<think>示例</think>\n```',
    'SYNTHETIC_REASONING没有协议标记，无法自动辨别', ' <thing>普通文本', '  普通答案'])
def test_normal_content_is_preserved_without_global_substitution(text):
    parser = FinalContent()
    assert ''.join(parser.feed(char) for char in text) + parser.finish() == text


def test_multiple_nested_leading_blocks_and_bounded_reasoning_tail():
    parser = FinalContent()
    output = []
    for char in ' \n<think>' + 'a' * 10000 + '<think>nested</think></think> <think>next</think>答案':
        output.append(parser.feed(char))
        assert len(parser.pending) <= 64
    assert ''.join(output) + parser.finish() == '答案'


@pytest.mark.parametrize('text', ['<think>未结束', '<thi', '<think>文本</thi'])
def test_unclosed_protocol_does_not_expose_reasoning_or_claim_complete(text):
    parser = FinalContent()
    assert parser.feed(text) == ''
    with pytest.raises(ValueError, match='answer_reasoning_incomplete'): parser.finish()


def test_empty_and_whitespace_do_not_create_a_final_answer():
    parser = FinalContent()
    assert parser.feed('') == parser.feed('  ') == ''
    assert parser.finish() == '  '


@pytest.mark.parametrize('pieces', [(' ' * 65 + TEXT,), (' ' * 65, TEXT)])
def test_excessive_leading_whitespace_has_same_bound_across_chunks(pieces):
    parser = FinalContent()
    with pytest.raises(ValueError, match='answer_prefix_too_large'):
        for piece in pieces: parser.feed(piece)


def test_json_drops_separate_reasoning_preserves_role_tools_and_usage_without_fallback():
    tool = [{'id': 'synthetic', 'type': 'function', 'function': {'name': 'example', 'arguments': '<think>literal</think>'}}]
    packet = {'id': 'synthetic', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
        'message': {'role': 'assistant', 'reasoning_content': 'SYNTHETIC_REASONING', 'content': TEXT, 'tool_calls': tool}}], 'usage': USAGE}
    result = final_response(packet)
    assert result['choices'][0]['message'] == {'role': 'assistant', 'content': '合成最终答案', 'tool_calls': tool}
    assert result['usage'] == USAGE and packet['choices'][0]['message']['content'] == TEXT
    for content in (None, ''):
        value = final_response({'choices': [{'message': {'content': content, 'reasoning_content': 'secret'}}]})
        assert value['choices'][0]['message']['content'] == content
        assert 'reasoning_content' not in value['choices'][0]['message']


def test_mixed_stream_choices_role_and_function_arguments_remain_separate():
    parser = FinalStream()
    tool = [{'index': 0, 'function': {'arguments': '<think>literal</think>'}}]
    packet = {'choices': [{'index': 0, 'delta': {'role': 'assistant', 'reasoning_content': 'secret', 'content': '<thi', 'tool_calls': tool}},
        {'index': 1, 'delta': {'content': '普通答案'}}], 'usage': USAGE}
    result = parser.packet(packet)
    assert result['choices'][0]['delta'] == {'role': 'assistant', 'content': '', 'tool_calls': tool}
    assert result['choices'][1]['delta']['content'] == '普通答案'
    result = parser.packet({'choices': [{'index': 0, 'delta': {'content': 'nk>秘密</think>答案'}, 'finish_reason': 'stop'}]})
    assert result['choices'][0]['delta']['content'] == '答案'
    assert result['choices'][0]['finish_reason'] == 'stop'
    parser.finish()


class Handler:
    def __init__(self, writer=None): self.wfile = writer or BytesIO(); self.close_connection = False
    def send_response(self, status): self.status = status
    def send_header(self, *args): pass
    def end_headers(self): pass
    def respond(self, status, body): self.status = status


def wire(packet): return b'data: ' + json.dumps(packet).encode() + b'\r\n\r\n'


def received(handler):
    return [json.loads(line[5:]) for line in handler.wfile.getvalue().splitlines()
        if line.startswith(b'data:') and line[5:].strip() != b'[DONE]']


def make_gateway(tmp_path, *, remote=None, stream=None):
    budget = FreeCampusCalls(tmp_path / 'synthetic-calls.sqlite3', proof={'request_model': 'synthetic-campus'}, create=True)
    settings = ModelSettings(provider='openai_compatible', model='synthetic-campus',
        base_url='https://synthetic.invalid/v1', api_key='synthetic-only')
    return ModelGateway(settings=settings, budget=budget, encoder=SimpleNamespace(identity='f' * 64),
        free_policy_verified=True, remote=remote, remote_stream=stream), budget


def request(stream=True): return {'model': 'synthetic-campus', 'stream': stream, 'max_tokens': 512, 'messages': []}


@pytest.mark.parametrize('phase', ['answer', 'probe'])
def test_nonstream_gateway_normalizes_json_once_and_preserves_settlement(tmp_path, phase):
    calls = []
    def remote(payload):
        calls.append(json.loads(payload))
        return 200, json.dumps({'choices': [{'message': {'content': TEXT, 'reasoning_content': 'secret', 'role': 'assistant'}}], 'usage': USAGE}).encode()
    gateway, budget = make_gateway(tmp_path, remote=remote)
    try:
        status, body = gateway.complete(phase, request(False))
        assert status == 200 and body['choices'][0]['message'] == {'role': 'assistant', 'content': '合成最终答案'}
        assert body['usage'] == USAGE and budget.status()['unknown_or_inflight'] == 0
        assert len(calls) == 1 and calls[0]['thinking'] == {'type': 'disabled'}
    finally: gateway.close()


@pytest.mark.parametrize('phase', ['hy', 'baseline'])
def test_internal_extraction_response_does_not_use_answer_projection(tmp_path, phase):
    original = {'choices': [{'message': {'content': TEXT, 'reasoning_content': 'synthetic-internal'}}], 'usage': USAGE}
    gateway, budget = make_gateway(tmp_path, remote=lambda payload: (200, json.dumps(original).encode()))
    try:
        status, result = gateway.complete(phase, {**request(False), 'messages': [{'role': 'system', 'content': '合成提取'}]})
        assert status == 200 and result == original and budget.status()['unknown_or_inflight'] == 0
    finally: gateway.close()


def test_nonstream_unclosed_reasoning_returns_fixed_error_and_unknown(tmp_path):
    gateway, budget = make_gateway(tmp_path, remote=lambda payload: (200, json.dumps({
        'choices': [{'message': {'content': '<think>synthetic-hidden'}}], 'usage': USAGE}).encode()))
    try:
        status, result = gateway.complete('answer', request(False))
        assert status == 502 and result == {'error': 'selected_provider_transport_failed'}
        assert budget.status()['attempt_count'] == budget.status()['unknown_or_inflight'] == 1
    finally: gateway.close()


def test_reasoning_only_or_tool_only_stream_has_no_fabricated_final_text():
    parser = FinalStream()
    assert parser.packet({'choices': [{'delta': {'content': None, 'reasoning_content': 'secret'}}]}) == {
        'choices': [{'delta': {'content': None}}]}
    tool = [{'index': 0, 'function': {'name': 'example', 'arguments': '{}'}}]
    assert parser.packet({'choices': [{'delta': {'tool_calls': tool}, 'finish_reason': 'tool_calls'}]}) == {
        'choices': [{'delta': {'tool_calls': tool}, 'finish_reason': 'tool_calls'}]}
    assert parser.packet({'choices': [], 'usage': USAGE}) == {'choices': [], 'usage': USAGE}
    parser.finish()


def test_empty_and_null_delta_end_packets_preserve_original_metadata():
    parser = FinalStream()
    for delta in ({}, None):
        packet = {'choices': [{'index': 0, 'delta': delta, 'finish_reason': 'stop'}]}
        assert parser.packet(packet) == packet
    assert parser.packet({'choices': [], 'usage': USAGE}) == {'choices': [], 'usage': USAGE}
    parser.finish()


def test_gateway_stream_filters_before_any_downstream_write_and_keeps_usage_done(tmp_path):
    calls, closed = [], []
    @contextmanager
    def remote(payload):
        calls.append(payload)
        def lines():
            chunks = [{'role': 'assistant', 'reasoning_content': 'SYNTHETIC_REASONING', 'content': None}]
            chunks += [{'content': char} for char in TEXT]
            for delta in chunks:
                yield from wire({'choices': [{'index': 0, 'delta': delta}]}).splitlines(keepends=True)
            yield from wire({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': USAGE}).splitlines(keepends=True)
            yield b'data: [DONE]\r\n'; yield b'\r\n'
        try: yield 200, lines()
        finally: closed.append(True)
    gateway, budget = make_gateway(tmp_path, stream=remote)
    handler = Handler()
    try:
        gateway.stream(request(), handler)
        packets = received(handler)
        content = ''.join(choice.get('delta', {}).get('content') or '' for packet in packets for choice in packet['choices'])
        assert content == '合成最终答案' and b'SYNTHETIC_REASONING' not in handler.wfile.getvalue()
        assert all('reasoning_content' not in choice['delta'] for packet in packets for choice in packet['choices'])
        assert packets[0]['choices'][0]['delta']['role'] == 'assistant'
        assert packets[-1]['usage'] == USAGE and handler.wfile.getvalue().endswith(b'data: [DONE]\n\n')
        assert budget.status()['unknown_or_inflight'] == 0 and len(calls) == len(closed) == 1
    finally: gateway.close()


@pytest.mark.parametrize('failure', ['unclosed', 'cancel_first_packet', 'invalid_json'])
def test_protocol_failure_or_first_packet_cancel_closes_once_and_retains_unknown(tmp_path, failure):
    calls, closed = [], []
    @contextmanager
    def remote(payload):
        calls.append(payload)
        def lines():
            if failure == 'invalid_json': yield b'data: not-json\n'; yield b'\n'
            else: yield from wire({'choices': [{'delta': {'content': '<think>secret'}}]}).splitlines(keepends=True)
            yield from wire({'choices': [], 'usage': USAGE}).splitlines(keepends=True)
            yield b'data: [DONE]\n'; yield b'\n'
        try: yield 200, lines()
        finally: closed.append(True)
    class Abort(BytesIO):
        def write(self, data): raise BrokenPipeError()
    gateway, budget = make_gateway(tmp_path, stream=remote)
    handler = Handler(Abort() if failure == 'cancel_first_packet' else None)
    try:
        gateway.stream(request(), handler)
        assert len(calls) == len(closed) == 1 and budget.status()['unknown_or_inflight'] == 1
        assert b'secret' not in handler.wfile.getvalue() and b'[DONE]' not in handler.wfile.getvalue()
        assert gateway.responses[-1]['failure'] == ('client_disconnected' if failure == 'cancel_first_packet' else 'stream_invalid')
    finally: gateway.close()
