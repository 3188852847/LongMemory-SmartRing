import importlib.util
from pathlib import Path
import sys
import types
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


def test_cosyvoice_greeting_archives_l0_and_queues_preset_without_model(monkeypatch):
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

    assert connection.chat("你好！") is True
    assert original == []
    assert archived == ["你好！"]
    assert paths == ["preset"]
    assert [item.role for item in messages] == ["user", "assistant"]
    assert [item.sentence_type for item in queued] == ["first", "middle", "last"]
    assert queued[1].content_detail == "你好呀，我在呢。"
