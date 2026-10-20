"""CPU-only gateway -> real installed OpenAI SDK -> pinned voice text contract.

Only synthetic data and a new test ledger. Never owner config, TTS or real provider.
The source root/head are explicit so V's candidate is tested without importing stale X code.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

FIXTURES = Path(__file__).resolve().parent
ROOT = FIXTURES.parents[1]


def child(config):
    import socket
    def audit(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
                raise RuntimeError('synthetic_consumer_external_network_forbidden')
    sys.addaudithook(audit)
    sys.path.insert(0, str(FIXTURES))
    import httpx
    import openai
    from openai.types import CompletionUsage
    from xiaozhi_voice_boundary_driver import load_snapshot, voice_text
    module = load_snapshot()
    module.CompletionUsage = CompletionUsage
    llm = object.__new__(module.LLMProvider)
    llm.model_name, llm.base_url = 'deepseek-v4-flash', config['base'] + '/voice/v1'
    llm.max_tokens = 64
    llm.temperature = llm.top_p = llm.frequency_penalty = None
    with openai.OpenAI(base_url=llm.base_url, api_key=config['token'], max_retries=0,
            http_client=httpx.Client(trust_env=False), timeout=10) as client:
        llm.client = client
        result = voice_text(functions=config['functions'], llm=llm, module=module)
    return {key: value for key, value in result.items() if key not in ('connection', 'sentence_ids', 'requests')}


def main():
    if sys.argv[1:] == ['--child']:
        print(json.dumps(child(json.loads(sys.stdin.buffer.read(65536))), ensure_ascii=False))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--voice-python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-clean-answer', action='store_true')
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.output.resolve()
    assert output.is_relative_to(ROOT/'data/test-tmp') and not output.exists()
    def identity():
        assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']).strip()
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip()
        assert head == args.expected_head
        return head
    identity()
    output.mkdir(parents=True)
    sys.path.insert(0, str(source/'src'))
    from longmemory.methods.hy_memory.model_gateway import ModelGateway
    from longmemory.methods.hy_memory.budget import SharedBudget, PricePolicy
    from longmemory.infrastructure.config.settings import ModelSettings
    from xiaozhi_voice_boundary_driver import wire
    usage = {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}
    cases = {
        'reasoning_field': [wire(reasoning_content='synthetic-internal'), wire('合成回答。')],
        'think_complete': [wire('<think>synthetic-internal'), wire('</think>合成回答。')],
        'think_fragmented': [wire(t) for t in ('<thi','nk>','synthetic-internal','</thi','nk>','合成回答。')],
        'analysis_fragmented': [wire(t) for t in ('<anal','ysis>','synthetic-internal','</analysis>','合成回答。')],
        'normal_words': [wire('合成回答包含 analysis 和 think 普通词。')],
    }
    rows = []
    for name, events in cases.items():
        expected = '合成回答包含 analysis 和 think 普通词。' if name == 'normal_words' else '合成回答。'
        frames = []
        for event in events:
            packet = {'id':'synthetic-stream','created':0,'object':'chat.completion.chunk',
                'model':'deepseek-v4-flash', **event}
            for choice in packet['choices']: choice.setdefault('index', 0)
            frames.append(('data: '+json.dumps(packet,ensure_ascii=False)+'\n\n').encode())
        frames += [('data: '+json.dumps({'id':'synthetic-stream','created':0,'object':'chat.completion.chunk',
            'model':'deepseek-v4-flash','choices':[], 'usage':usage})+'\n\n').encode(), b'data: [DONE]\n\n']
        lines = b''.join(frames).splitlines(keepends=True)
        for functions in (False, True):
            called = []
            @contextmanager
            def remote_stream(payload):
                called.append(True)
                body=json.loads(payload)
                assert body['thinking']=={'type':'disabled'} and body['stream_options']['include_usage']
                yield 200, iter(lines)
            folder = output/f'{name}-{int(functions)}'
            folder.mkdir()
            budget = SharedBudget(folder/'synthetic-budget.db',
                policy=PricePolicy(expires_at_unix=time.time()+3600), create=True)
            settings = ModelSettings(provider='openai_compatible', base_url='http://127.0.0.1:9',
                api_key='synthetic-never-remote', model='deepseek-v4-flash', allow_http=True)
            with ModelGateway(settings=settings, budget=budget, encoder=None,
                    currency_verified=True, remote_stream=remote_stream) as gateway:
                config={'base':gateway.base,'token':gateway.token,'functions':functions}
                result=subprocess.run([str(args.voice_python),'-I','-B','-X','utf8',str(Path(__file__)), '--child'],
                    input=json.dumps(config).encode(),capture_output=True,cwd=folder,timeout=20,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                assert result.returncode==0, result.stderr.decode('utf-8',errors='replace')[-1200:]
                data=json.loads(result.stdout)
            state=budget.report()
            assert len(called)==1 and state['attempt_count']==1 and state['unknown_or_inflight']==0
            common=data['tts_input_text']==data['stored_sentence_text']==data['assistant_text']
            row={'case':name,'functions':functions,'common_text_sinks_equal':common,
                'answer_exact':common and data['tts_input_text']==expected,
                'internal_sentinel_emitted':'synthetic-internal' in data['tts_input_text'],
                'completed':data['completed'],'gateway_mock_attempts':len(called),
                'budget_unknown_or_inflight':state['unknown_or_inflight']}
            rows.append(row)
    assert identity()==args.expected_head
    report={'source_head':args.expected_head,'real_external_model_calls':0,'tts_or_gpu':False,
        'personal_config_or_database':False,'real_installed_openai_sdk':True,
        'pinned_native_methods':True,'rows':rows,'all_clean_answers':all(r['answer_exact'] for r in rows)}
    path=output/'report.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**report},ensure_ascii=False))
    if args.require_clean_answer: assert report['all_clean_answers']


if __name__ == '__main__':main()
