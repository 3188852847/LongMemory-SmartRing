"""真实协议形状的离线消息流：不导入 websockets、不访问付费云服务。"""

import asyncio
import base64
import importlib
import json
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"))
client_module = importlib.import_module("doubao_realtime.client")
config_module = importlib.import_module("doubao_realtime.config")


class FakeSocket:
    def __init__(self, *, auto_session=True, auto_close=True, auto_cancel=True):
        self.frames = asyncio.Queue()
        self.sent = []
        self.times = []
        self.closed = False
        self.auto_session = auto_session
        self.auto_close = auto_close
        self.auto_cancel = auto_cancel

    async def send(self, frame):
        payload = json.loads(frame)
        self.sent.append(payload)
        self.times.append(asyncio.get_running_loop().time())
        event_type = payload["type"]
        if event_type == "session.create" and self.auto_session:
            self.feed({"type": "session.created", "session": {"id": "synthetic-session"}})
        if event_type == "session.close" and self.auto_close:
            self.feed({"type": "session.closed"})
        if event_type == "response.cancel" and self.auto_cancel:
            self.feed({"type": "response.canceled", "event_id": "server-generated-id"})

    def feed(self, payload):
        self.frames.put_nowait(json.dumps(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self.frames.get()
        if frame is None:
            raise StopAsyncIteration
        return frame

    async def close(self):
        self.closed = True
        self.frames.put_nowait(None)


def make_client(socket=None, **kwargs):
    socket = socket or FakeSocket()
    connection_calls = []

    async def factory(url, **options):
        connection_calls.append((url, options))
        return socket

    client = client_module.DoubaoRealtimeClient(
        config_module.DoubaoConfig(api_key="synthetic-key"), connect_factory=factory,
        timeout=0.2, close_timeout=0.02, **kwargs)
    return client, socket, connection_calls


def test_session_audio_contract_and_pacing():
    async def scenario():
        client, socket, calls = make_client()
        await client.connect()
        assert calls[0][0] == config_module.OFFICIAL_URL
        assert calls[0][1]["additional_headers"] == {"X-Api-Key": "synthetic-key"}
        session = socket.sent[0]
        assert session["type"] == "session.create"
        assert session["session"]["model"] == "1.2.6.1"
        assert session["session"]["audio"]["input"]["format"] == {"type": "pcm", "rate": 16000}
        assert session["session"]["audio"]["output"]["format"] == {"type": "pcm", "rate": 24000}
        assert "tools" not in session["session"]
        assert socket.sent[1]["type"] == "input_audio_mute.commit"
        await client.start_listening()
        # 设备侧60ms音频由客户端分成3个20ms包，不能一次突发上传。
        pcm = b"\x01\x02" * 1000
        await client.send_audio(pcm)
        await client.stop_listening()
        await client.commit()
        audio = [(payload, time) for payload, time in zip(socket.sent, socket.times)
                 if payload["type"] == "input_audio_buffer.append"]
        assert len(audio) == 4
        packets = [base64.b64decode(payload["audio"]) for payload, _ in audio]
        assert all(len(packet) == 640 for packet in packets)
        assert b"".join(packets) == pcm.ljust(2560, b"\0")
        # Windows定时器允许单包抖动；整体不能突发，精确节拍用下方虚拟时钟验证。
        assert audio[-1][1] - audio[0][1] >= 0.055
        assert socket.sent[-2]["type"] == "input_audio_mute.commit"
        assert socket.sent[-1]["type"] == "input_audio_buffer.commit"
        await client.say_text("合成测试话术")
        assert socket.sent[-1]["type"] == "speech_text_buffer.commit"
        assert socket.sent[-1]["text"] == "合成测试话术"
        await client.close()
        await client.close()
        assert socket.closed
        assert sum(p["type"] == "session.close" for p in socket.sent) == 1
    asyncio.run(scenario())


def test_early_timer_wake_and_one_late_wake_do_not_burst_or_accumulate_delay():
    """覆盖Windows旧事件循环：可能提前唤醒，也可能偶发晚一个时钟刻度。"""
    async def scenario():
        current = 1.0
        sleeps = 0
        sent = []
        async def sleep(delay):
            nonlocal current, sleeps
            sleeps += 1
            # 一次32ms迟到；其他等待模拟提前4ms唤醒，必须再次核对时钟。
            current += delay + 0.032 if sleeps == 1 else max(0.0005, delay - 0.004)
        client, socket, _ = make_client(clock=lambda: current, sleep=sleep)
        await client.connect()
        original = socket.send
        async def send(frame):
            if json.loads(frame)["type"] == "input_audio_buffer.append":
                sent.append(current)
            await original(frame)
        socket.send = send
        await client.start_listening()
        for _ in range(100):
            await client.send_audio(bytes(640))
        assert min(b-a for a,b in zip(sent, sent[1:])) >= 0.010 - 1e-9
        assert abs(sent[-1] - sent[0] - 99 * 0.020) < 0.003
        await client.close()
    asyncio.run(scenario())


def test_real_transcription_schema_and_missing_start_id():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        socket.feed({"type": "conversation.item.input_audio_transcription.started", "item_id": ""})
        socket.feed({"type": "conversation.item.input_audio_transcription.delta",
                     "item_id": "user-1", "content_index": 0, "delta": "合成"})
        socket.feed({"type": "conversation.item.input_audio_transcription.completed",
                     "item_id": "user-1", "content_index": 0, "transcript": "合成问题。"})
        socket.feed({"type": "response.output_audio.started", "question_id": "q-1",
                     "response_id": "", "tts_type": "default"})
        socket.feed({"type": "response.output_audio.delta", "question_id": "q-1",
                     "response_id": "r-1", "delta": base64.b64encode(b"\x01\x02").decode()})
        socket.feed({"type": "response.output_text.delta", "question_id": "q-1",
                     "response_id": "r-1", "delta": "合成回答。"})
        socket.feed({"type": "response.output_audio.done", "question_id": "q-1", "response_id": "r-1"})
        events = [await asyncio.wait_for(client.receive(), 0.2) for _ in range(7)]
        assert [e.kind for e in events] == ["speech_started", "transcript", "transcript",
                                             "response_started", "audio", "text", "response_done"]
        assert not events[1].is_final
        assert events[2].is_final and events[2].text == "合成问题。"
        assert events[2].item_id == "user-1" and not events[2].question_id
        assert events[4].audio == b"\x01\x02" and events[4].response_id == "r-1"
        assert "合成回答" not in repr(events[5])
        await client.close()
    asyncio.run(scenario())


def test_cancel_ack_does_not_cancel_new_answer_and_late_audio_is_dropped():
    async def scenario():
        client, socket, _ = make_client(FakeSocket(auto_cancel=False))
        await client.connect()
        socket.feed({"type": "response.output_audio.started", "response_id": "old", "question_id": "q1"})
        assert (await client.receive()).response_id == "old"
        cancel = asyncio.create_task(client.interrupt())
        await asyncio.sleep(0)
        socket.feed({"type": "conversation.item.input_audio_transcription.started", "item_id": "user-new"})
        socket.feed({"type": "response.output_audio.started", "response_id": "new", "question_id": "q2"})
        socket.feed({"type": "response.canceled", "event_id": "server-cancel"})
        socket.feed({"type": "response.output_audio.delta", "response_id": "old", "delta": "AQI="})
        socket.feed({"type": "response.output_audio.delta", "response_id": "new", "delta": "AwQ="})
        await cancel
        events = [await asyncio.wait_for(client.receive(), 0.2) for _ in range(4)]
        assert [(e.kind, e.response_id) for e in events] == [
            ("speech_started", ""), ("response_started", "new"), ("canceled", "old"), ("audio", "new")]
        await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [
    b"binary-old-protocol", "not-json", "[]",
    json.dumps({"type": "error", "message": "private-synthetic-key-and-user-content"}),
    json.dumps({"type": "response.output_audio.delta", "response_id": "r", "delta": "invalid-base64"}),
    json.dumps({"type": "response.output_audio.delta", "response_id": "r", "delta": "AQ=="}),
    json.dumps({"type": "response.output_audio.delta", "response_id": "r",
                "delta": base64.b64encode(bytes(192002)).decode()}),
], ids=["binary", "invalid-json", "array", "cloud-error", "bad-base64", "odd-pcm", "oversized-pcm"])
def test_bad_frames_fail_closed_without_disclosing_raw_content(bad):
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        socket.feed({"type": "response.output_audio.started", "response_id": "r"})
        assert (await client.receive()).kind == "response_started"
        socket.frames.put_nowait(bad)
        event = await asyncio.wait_for(client.receive(), 0.2)
        assert event.kind == "error"
        assert "private-synthetic" not in repr(event)
        assert (await client.receive()) is None
        await client.close()
        assert socket.closed
    asyncio.run(scenario())


def test_session_timeout_closes_socket_and_exposes_only_fixed_error():
    async def scenario():
        client, socket, _ = make_client(FakeSocket(auto_session=False, auto_close=False))
        with pytest.raises(client_module.RealtimeError, match="realtime_connect_failed"):
            await client.connect()
        assert socket.closed
    asyncio.run(scenario())


def test_cancel_timeout_closes_socket():
    async def scenario():
        client, socket, _ = make_client(FakeSocket(auto_cancel=False))
        await client.connect()
        with pytest.raises(client_module.RealtimeError, match="realtime_cancel_timeout"):
            await client.interrupt()
        assert socket.closed
    asyncio.run(scenario())


def test_muted_input_and_invalid_pcm_are_rejected():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        with pytest.raises(client_module.RealtimeError, match="microphone_muted"):
            await client.send_audio(b"\0\0")
        await client.start_listening()
        for audio in (b"", b"\0", "text", b"\0" * 32002):
            with pytest.raises(client_module.RealtimeError, match="invalid_input_audio"):
                await client.send_audio(audio)
        await client.close()
    asyncio.run(scenario())


def test_pacing_compensates_small_timer_overshoot_and_resets_large_stall():
    async def scenario():
        current = [1.0]
        sends = []

        async def sleep(delay):
            current[0] += delay + 0.002  # 可复现的2ms定时器超调，不等待真实时钟。

        client, socket, _ = make_client(clock=lambda: current[0], sleep=sleep)
        original_send = socket.send

        async def send(frame):
            if json.loads(frame)["type"] == "input_audio_buffer.append":
                sends.append(current[0])
                current[0] += 0.002  # 每包2ms发送开销也不能永久叠加到20ms。
            await original_send(frame)

        socket.send = send
        await client.connect()
        await client.start_listening()
        for _ in range(100):
            await client.send_audio(bytes(640))
        assert sends[-1] - sends[0] == pytest.approx(99 * 0.02 + 0.002)
        current[0] += 1.0  # 长阻塞不能转化为十几包瞬时追发。
        await client.send_audio(bytes(640 * 3))
        assert sends[-1] - sends[-3] >= 0.04
        await client.close()
    asyncio.run(scenario())


def test_unidentified_previous_response_fails_closed_on_next_speech():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        socket.feed({"type": "conversation.item.input_audio_transcription.completed", "transcript": "旧问题"})
        assert (await client.receive()).is_final
        socket.feed({"type": "conversation.item.input_audio_transcription.started", "item_id": "new-user"})
        event = await client.receive()
        assert event.kind == "error" and event.code == "realtime_turn_ambiguous"
        assert await client.receive() is None
        await client.close()
        assert socket.closed
    asyncio.run(scenario())


def test_empty_final_and_same_utterance_partials_do_not_trigger_ambiguity():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        for payload in [
            {"type": "conversation.item.input_audio_transcription.started"},
            {"type": "conversation.item.input_audio_transcription.delta", "delta": ""},
            {"type": "conversation.item.input_audio_transcription.delta", "delta": "合成"},
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": " "},
            {"type": "conversation.item.input_audio_transcription.started"},
        ]:
            socket.feed(payload)
        events = [await client.receive() for _ in range(5)]
        assert all(event.kind != "error" for event in events)
        assert events[-1].kind == "speech_started"
        await client.close()
    asyncio.run(scenario())


def test_blocked_send_and_graceful_close_have_time_bounds():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()

        async def blocked(frame):
            await asyncio.Future()

        socket.send = blocked
        with pytest.raises(client_module.RealtimeError, match="realtime_send_failed"):
            await asyncio.wait_for(client.say_text("合成话术"), 0.4)
        await asyncio.wait_for(client.close(), 0.2)
        assert socket.closed
    asyncio.run(scenario())


def test_close_does_not_wait_for_a_blocked_upload_lock():
    async def scenario():
        client, socket, _ = make_client()
        await client.connect()
        started = asyncio.Event()

        async def blocked(frame):
            started.set()
            await asyncio.Future()

        socket.send = blocked
        upload = asyncio.create_task(client.say_text("合成文本"))
        await started.wait()
        await asyncio.wait_for(client.close(), 0.15)
        assert socket.closed
        upload.cancel()
        await asyncio.gather(upload, return_exceptions=True)
    asyncio.run(scenario())
