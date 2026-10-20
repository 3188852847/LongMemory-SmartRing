"""Run pinned provider/chat methods with synthetic chunks, queues and no runtime imports."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlparse
import uuid

FIXTURE = Path(__file__).with_name('xiaozhi_voice_snapshot_eb4b28c.py')


class Log:
    def __init__(self):
        self.errors = []
    def bind(self, **kwargs): return self
    def info(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): self.errors.append(args)


class CompletionUsage:
    def __init__(self, **kwargs): self.__dict__.update(kwargs)


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
    def __iter__(self): return iter(self.chunks)
    def close(self): self.closed = True


def load_snapshot():
    spec = importlib.util.spec_from_file_location('fixed_xiaozhi_voice_methods', FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.urlparse = urlparse
    module.CompletionUsage = CompletionUsage
    module.logger = Log()
    module.TAG = 'synthetic-voice-boundary'
    module.uuid, module.json = uuid, json
    module.Message = NS
    module.TTSMessageDTO = NS
    module.ContentType = NS(TEXT='text', ACTION='action')
    module.SentenceType = NS(FIRST='first', MIDDLE='middle', LAST='last')
    module.DIRECT_ANSWER_TOOL = {'type': 'function', 'function': {'name': 'direct_answer'}}
    module.get_system_error_response = lambda _config: 'synthetic-system-error'
    return module


def _object(value):
    if isinstance(value, dict): return NS(**{key: _object(item) for key, item in value.items()})
    if isinstance(value, list): return [_object(item) for item in value]
    return value


def sdk_chunks(wire_events):
    chunks = []
    for event in wire_events:
        chunk = _object(event)
        if event.get('usage') is not None:
            chunk.usage = CompletionUsage(**event['usage'])
        chunks.append(chunk)
    return chunks


def wire(content=None, **extra):
    delta = dict(extra)
    if content is not None: delta['content'] = content
    return {'choices': [{'delta': delta, 'finish_reason': None}]}


def provider(wire_events, *, module=None):
    module = module or load_snapshot()
    instance = object.__new__(module.LLMProvider)
    instance.model_name = 'synthetic-model'
    instance.base_url = 'http://127.0.0.1:9/voice/v1'
    for name in ('max_tokens', 'temperature', 'top_p', 'frequency_penalty'):
        setattr(instance, name, None)
    streams, requests = [], []
    def create(**kwargs):
        requests.append(kwargs)
        stream = Stream(sdk_chunks(wire_events))
        streams.append(stream)
        return stream
    instance.client = NS(chat=NS(completions=NS(create=create)))
    return instance, streams, requests


class Dialogue:
    def __init__(self): self.dialogue = []
    def put(self, item): self.dialogue.append(item)
    def get_llm_dialogue_with_memory(self, *_args): return []
    def get_llm_dialogue(self): return []


def voice_text(wire_events=(), *, functions=False, connection=None, llm=None, module=None):
    """No audio synthesis: returns the fixed chat's shared text inputs and completion."""
    module = module or load_snapshot()
    if llm is None:
        llm, streams, requests = provider(wire_events, module=module)
    else:
        streams, requests = [], []
    if connection is None:
        queue, subtitles = [], []
        connection = NS(logger=Log(), dialogue=Dialogue(), memory=None, current_speaker='',
            session_id='synthetic-session',
            system_introduced_speakers=set(), features={'emoji': False}, client_abort=False,
            config={'voiceprint': {}}, func_handler=NS(get_functions=lambda: []),
            tts=NS(tts_text_queue=NS(put=queue.append),
                store_tts_text=lambda identity, text: subtitles.append((identity, text))))
        connection._synthetic_queue = queue
        connection._synthetic_subtitles = subtitles
    queue_start, subtitle_start = len(connection._synthetic_queue), len(connection._synthetic_subtitles)
    dialogue_start = len(connection.dialogue.dialogue)
    connection.intent_type = 'function_call' if functions else 'nointent'
    connection.llm = llm
    result = module.chat(connection, '合成问题', 0)
    if connection.logger.errors:
        raise AssertionError(('fixed_chat_did_not_complete_expected_branch', connection.logger.errors))
    events = connection._synthetic_queue[queue_start:]
    text = ''.join(getattr(item, 'content_detail', '') for item in events
        if getattr(item, 'content_type', None) == 'text')
    stored_text = ''.join(text for _, text in connection._synthetic_subtitles[subtitle_start:])
    assistant = ''.join(item.content for item in connection.dialogue.dialogue[dialogue_start:]
        if item.role == 'assistant')
    return {'tts_input_text': text, 'stored_sentence_text': stored_text, 'assistant_text': assistant,
        'sentence_ids': {item.sentence_id for item in events}, 'completed': result,
        'streams_closed': all(stream.closed for stream in streams), 'requests': requests,
        'connection': connection}
