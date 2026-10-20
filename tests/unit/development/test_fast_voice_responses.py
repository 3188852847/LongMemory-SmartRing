import importlib.util
import json
from pathlib import Path
import sys
import types
import pytest
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/fast_voice_responses.py"
spec = importlib.util.spec_from_file_location("fast_voice_responses_test", SCRIPT)
fast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fast)


def test_fast_response_matches_only_complete_closed_intents():
    assert fast.fast_response_for("你好！") == "你好呀，我在呢。"
    assert fast.fast_response_for(" 你 还 在 吗？ ") == "我在，听得到。"
    assert fast.fast_response_for("HELLO") == "你好呀，我在呢。"
    assert fast.fast_response_for("你好，帮我看看明天的安排") is None
    assert fast.fast_response_for("你在吗，我想问一件事") is None
    assert fast.fast_response_for(None) is None


def test_fast_response_assets_cover_every_reply():
    assert {
        fast.fast_asset_for_text(response)
        for response in fast._QUERY_RESPONSES.values()
    } == set(fast.FAST_RESPONSE_ASSETS.values())
    root = SCRIPT.parents[3] / "assets/audio/voice-fastpath/cosyvoice3"
    for name in fast.FAST_RESPONSE_ASSETS.values():
        assert (root / name).stat().st_size > 44


@pytest.mark.parametrize('payload', [
    {'content': '你好。', 'language': 'zh', 'emotion': 'neutral'},
    {'content': '你好。', 'speaker': 'synthetic-speaker', 'role': 'user'},
])
def test_asr_envelope_matches_the_same_archived_user_text(payload):
    spec = importlib.util.spec_from_file_location('asr_input_mapping_test',
        SCRIPT.parents[3] / 'src/longmemory/entrypoints/xiaozhi/mapping.py')
    mapping = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapping)
    query = json.dumps(payload, ensure_ascii=False)
    assert mapping.extract_user_text(query) == '你好。'
    assert fast.fast_response_for(query) == fast.fast_response_for(mapping.extract_user_text(query))


@pytest.mark.parametrize('query', [
    '{bad-json', '{"content":null}', '{"content":{"text":"你好"}}',
    '{"speaker":"你好"}', '{"role":"assistant","content":"你好"}',
    '{"content":"你好，帮我搜索今天新闻"}', json.dumps({'content': '你' * 4001}),
    '{' * 16001,
])
def test_invalid_or_non_closed_asr_input_does_not_enter_fast_path(query):
    assert fast.fast_response_for(query) is None


def test_non_cosyvoice_backend_keeps_original_chat():
    calls = []

    class Connection:
        def chat(self, query, depth=0):
            calls.append((query, depth))
            return "original"

    fast.install_fast_voice_responses(Connection)
    connection = Connection()
    connection.config = {"selected_module": {"TTS": "EdgeTTS"}, "TTS": {}}
    assert connection.chat("你好") == "original"
    assert calls == [("你好", 0)]


def test_custom_voice_does_not_use_official_greeting_assets(monkeypatch):
    calls = []
    monkeypatch.setattr(fast, 'default_voice_active', lambda: False)
    class Connection:
        def chat(self, query, depth=0):
            calls.append((query, depth)); return 'normal-pipeline'
    fast.install_fast_voice_responses(Connection)
    connection = Connection()
    connection.config = {'selected_module': {'TTS': 'CustomTTS'}, 'TTS': {'CustomTTS': {'url': fast.COSYVOICE_URL}}}
    assert connection.chat('你好') == 'normal-pipeline'
    assert calls == [('你好', 0)]


@pytest.mark.parametrize('depth,selected,url', [
    (1, 'CustomTTS', fast.COSYVOICE_URL),
    (0, 'OtherTTS', fast.COSYVOICE_URL),
    (0, 'CustomTTS', fast.COSYVOICE_URL + '/'),
])
def test_asr_envelope_preserves_recursion_and_exact_backend_guards(monkeypatch, depth, selected, url):
    monkeypatch.setattr(fast, 'default_voice_active', lambda: True)
    calls = []
    class Connection:
        def chat(self, query, depth=0): calls.append((query, depth)); return 'original'
    fast.install_fast_voice_responses(Connection)
    connection = Connection()
    connection.config = {'selected_module': {'TTS': selected}, 'TTS': {selected: {'url': url}}}
    query = json.dumps({'content': '你好。', 'speaker': 'synthetic-speaker'})
    assert connection.chat(query, depth) == 'original'
    assert calls == [(query, depth)]


@pytest.mark.parametrize('query', ['你好！', json.dumps(
    {'content': '你好。', 'language': 'zh', 'emotion': 'neutral'}, ensure_ascii=False)])
def test_cosyvoice_greeting_archives_l0_and_queues_preset_without_model(monkeypatch, query):
    class DTO:
        def __init__(self, **values): self.__dict__.update(values)

    class Message:
        def __init__(self, **values): self.__dict__.update(values)

    dto = types.ModuleType("core.providers.tts.dto.dto")
    dto.ContentType = SimpleNamespace(ACTION="action", TEXT="text")
    dto.SentenceType = SimpleNamespace(FIRST="first", MIDDLE="middle", LAST="last")
    dto.TTSMessageDTO = DTO
    dialogue = types.ModuleType("core.utils.dialogue")
    dialogue.Message = Message
    for name in ("core", "core.providers", "core.providers.tts", "core.providers.tts.dto", "core.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto)
    monkeypatch.setitem(sys.modules, "core.utils.dialogue", dialogue)

    class Completed:
        def result(self): return ""

    archived = []
    def query_memory(query):
        archived.append(query)
        return SimpleNamespace(close=lambda: None)

    def submit(coroutine, _loop):
        coroutine.close()
        return Completed()

    monkeypatch.setattr(fast.asyncio, "run_coroutine_threadsafe", submit)
    original = []

    class Connection:
        def chat(self, query, depth=0): original.append((query, depth))

    fast.install_fast_voice_responses(Connection)
    queued, messages, logs = [], [], []
    connection = Connection()
    connection.config = {
        "selected_module": {"TTS": "CustomTTS"},
        "TTS": {"CustomTTS": {"url": fast.COSYVOICE_URL}},
    }
    connection.loop = object()
    connection.memory = SimpleNamespace(query_memory=query_memory)
    connection.dialogue = SimpleNamespace(put=messages.append)
    connection.tts = SimpleNamespace(tts_text_queue=SimpleNamespace(put=queued.append))
    paths = []
    connection._longmemory_voice_latency = SimpleNamespace(set_response_path=paths.append)
    connection.logger = SimpleNamespace(bind=lambda **_kw: SimpleNamespace(
        info=logs.append, warning=logs.append,
    ))

    monkeypatch.setattr(fast, 'default_voice_active', lambda: True)
    assert connection.chat(query) is True
    assert original == []
    assert archived == [query]
    assert paths == ["preset"]
    assert [item.role for item in messages] == ["user", "assistant"]
    assert [item.sentence_type for item in queued] == ["first", "middle", "last"]
    assert queued[1].content_detail == "你好呀，我在呢。"
