"""现有生产包装器的合成组合测试；不含真实 ASR/SDK/TTS/设备。

最终答案过滤、LLM/TTS 计时、发送观察和回答归档使用工作树真实实现；仅供应商、
音频、传输和记忆存储使用进程内替身。新 AB–AH 功能交付后再补真实适配器。
"""

import asyncio
from contextvars import ContextVar
import importlib.util
from itertools import count
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from longmemory.methods.hy_memory.answer_content import FinalStream


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
sys.path.insert(0, str(SCRIPTS))
import voice_diagnostics as diagnostics
import voice_latency as latency
import voice_prediction as prediction

spec = importlib.util.spec_from_file_location("ai_combination_launch", SCRIPTS / "launch_with_memory.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


@pytest.fixture
def chain(monkeypatch):
    # 禁止诊断投递触达任何运行服务；其他替身同样不持有网络/文件接口。
    events = []
    monkeypatch.setattr(diagnostics, "emit", lambda item: events.append(item))
    monkeypatch.setenv("LONGMEMORY_VOICE_RESPONSE_STYLE", "realtime")
    turn = ContextVar("synthetic_combination_turn", default=None)

    class Memory:
        def __init__(self):
            self.sequence = count(1)
            self.completed, self.cancelled, self.queries = [], [], []

        def begin_turn(self):
            key = next(self.sequence)
            return key, turn.set(key)

        def end_turn(self, token):
            turn.reset(token)

        async def query_memory(self, text):
            self.queries.append((turn.get(), text))
            return "合成记忆上下文"

        async def save_memory(self, *_args):
            raise AssertionError("synthetic combination must not persist")

        def record_completed_turn(self, text, *, turn_key):
            self.completed.append((turn_key, text))

        def cancel_turn(self, key, reason):
            self.cancelled.append((key, reason))

    class LLM:
        def __init__(self):
            self.requests, self.closed = [], 0
            self.mode = "normal"

        def response(self, session, dialogue):
            self.requests.append(dialogue)
            try:
                if self.mode == "failure":
                    raise TimeoutError("synthetic model timeout")
                parts = [] if self.mode == "empty" else ["<thi", "nk>synthetic-hidden", "</thi", "nk>合成", "回答。"]
                parser = FinalStream()
                for part in parts:
                    packet = parser.packet({"choices": [{"index": 0, "delta": {"content": part}}]})
                    yield packet["choices"][0]["delta"]["content"]
                parser.packet({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            finally:
                self.closed += 1

    class TTS:
        def __init__(self):
            self.inputs, self.packets = [], []
            self.current_sentence_id = None

        def to_tts_stream(self, text):
            self.inputs.append(text)
            self.handle_opus(b"synthetic-audio")

        def handle_opus(self, packet):
            self.packets.append(packet)

    class Dialogue:
        def __init__(self):
            self.dialogue = []

        def put(self, message):
            self.dialogue.append(message)

    class Connection:
        def __init__(self):
            self.memory, self.dialogue = Memory(), Dialogue()
            self.llm, self.tts = LLM(), TTS()
            self.provider = self.llm
            self.config = {"selected_module": {"TTS": "Synthetic", "Memory": "Synthetic"}}
            self.logger = SimpleNamespace(bind=lambda **_kwargs: SimpleNamespace(info=lambda *_args: None,
                                                                                error=lambda *_args: None))
            self.sentence_id, self.client_abort = "old", False
            self._longmemory_waiting_enabled = False
            self.serial = count(1)
            self.requests = []
            self.wire = []
            ticks = count(1)
            self._longmemory_voice_latency = latency.VoiceLatencyTracker(self, clock=lambda: next(ticks) / 1000)

        def chat(self, query, depth=0):
            self.sentence_id = "synthetic-" + str(next(self.serial))
            self.tts.current_sentence_id = self.sentence_id
            memory = asyncio.run(self.memory.query_memory(query))
            dialogue = [{"role": "system", "content": "合成角色：" + memory},
                        {"role": "user", "content": query}]
            self.requests.append(dialogue)
            answer = "".join(self.llm.response("synthetic", dialogue))
            if answer:
                self.dialogue.put(SimpleNamespace(role="assistant", content=answer))
                self.tts.to_tts_stream(answer)

                async def sender(_connection, _sentence_type, audios, _text, sentence_id=None):
                    self.wire.append((sentence_id, audios))

                asyncio.run(latency.observed_audio_sender(sender)(self, None, self.tts.packets[-1], None,
                                                                  self.sentence_id))
            return None  # 保留上游 direct_answer 返回 None 的真实契约。

    # 与现有启动顺序一致：计时在回答归档内部，影子观察器在外部。
    latency.install_voice_latency(Connection)
    launch.install_answer_completion(Connection)
    prediction.install_voice_prediction_shadow(Connection)
    connection = Connection()
    launch.observe_memory_operations(connection)
    return connection, events, turn


def test_real_wrappers_filter_reasoning_keep_system_order_and_complete_once(chain):
    connection, events, turn = chain
    for module in (launch, latency, prediction, diagnostics):
        assert Path(module.__file__).resolve().parent == SCRIPTS.resolve()
    assert connection.chat("合成用户提问") is None
    assert connection.memory.completed == [(1, "合成回答。")]
    assert connection.tts.inputs == ["合成回答。"]
    assert not connection.memory.cancelled
    assert len(connection.memory.queries) == len(connection.wire) == connection.provider.closed == 1
    assert connection.memory.queries[0][0] == 1
    assert turn.get() is None and diagnostics.CURRENT.get() is None
    assert [row["role"] for row in connection.provider.requests[0]] == ["system", "user"]
    assert "圆屏实时语音表达规则" in connection.provider.requests[0][0]["content"]
    assert "圆屏实时语音表达规则" not in connection.requests[0][0]["content"]
    snapshot = connection._longmemory_voice_latency.snapshot()
    assert snapshot["state"] == "first_audio_sent"
    assert snapshot["timings_ms"]["llm_first_output_ms"] < snapshot["timings_ms"]["first_audio_sent_ms"]
    assert "input_timings_ms" not in snapshot  # 未经过真实输入，不虚构停嘴时间。
    assert "playback" not in repr(snapshot)
    names = [row["event"] for row in events]
    assert names.index("chat_entered") < names.index("memory_requested") < names.index("model_output") < names.index("tts_audio_ready")
    assert "synthetic-hidden" not in repr(snapshot) + repr(events) + repr(connection.memory.completed)


def test_reinstalling_launch_completion_does_not_duplicate_memory_or_wrappers(chain):
    connection, _, _ = chain
    original = type(connection).chat
    launch.install_answer_completion(type(connection))
    latency.install_voice_latency(type(connection))
    prediction.install_voice_prediction_shadow(type(connection))
    assert type(connection).chat is original
    connection.chat("第一轮")
    connection.chat("第二轮")
    assert connection.memory.completed == [(1, "合成回答。"), (2, "合成回答。")]
    assert len(connection.wire) == connection.provider.closed == 2
    assert connection.memory.queries == [(1, "第一轮"), (2, "第二轮")]


@pytest.mark.parametrize("mode", ["empty", "failure"])
def test_model_failure_or_empty_result_cancels_completion_and_emits_no_audio(chain, mode):
    connection, events, turn = chain
    connection.provider.mode = mode
    if mode == "failure":
        with pytest.raises(TimeoutError, match="synthetic"):
            connection.chat("合成提问")
    else:
        connection.chat("合成提问")
    assert not connection.memory.completed and not connection.wire and not connection.tts.inputs
    assert connection.memory.cancelled == [(1, "chat_failed")]
    assert connection.provider.closed == 1
    assert turn.get() is None and diagnostics.CURRENT.get() is None
    assert connection._longmemory_voice_latency.snapshot()["timings_ms"]["first_audio_sent_ms"] is None
    assert "model_output" not in [row["event"] for row in events]


def test_cancelled_completion_is_not_archived_as_success(chain):
    connection, _, turn = chain
    # 此测试只证明现有归档门；原基线不因此获得 epoch 队列/真机残音证明。
    connection.client_abort = True
    connection.chat("合成提问")
    assert connection.memory.cancelled == [(1, "cancelled")]
    assert not connection.memory.completed
    assert turn.get() is None
