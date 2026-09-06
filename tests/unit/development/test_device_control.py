"""纯离线控制协议测试；模拟圆屏回执，不启动模型或接触真实圆屏。"""

import asyncio
import importlib.util
import json
import time
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/device_control.py"
spec = importlib.util.spec_from_file_location("device_control_tested", SCRIPT)
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class FakeClient:
    def __init__(self):
        self.ready = True
        self.next_id = 1
        self.call_results = {}
        self.tools = {
            "status": {"name": control.STATUS_TOOL, "inputSchema": {"type": "object"}},
            "volume": {"name": control.VOLUME_TOOL, "inputSchema": {
                "type": "object", "properties": {"volume": {
                    "type": "integer", "minimum": 0, "maximum": 100}}, "required": ["volume"]}},
        }

    async def get_next_id(self):
        value = self.next_id
        self.next_id += 1
        return value

    async def register_call_result_future(self, call_id, future):
        self.call_results[call_id] = future

    async def cleanup_call_result(self, call_id):
        self.call_results.pop(call_id, None)


class FakeSocket:
    def __init__(self, client):
        self.client = client
        self.state = SimpleNamespace(name="OPEN")
        self.calls = []
        self.volume = 45
        self.no_response = False
        self.set_error = False
        self.mismatch = False
        self.fail_after_set = False

    async def send(self, text):
        call = json.loads(text)["payload"]
        self.calls.append(call)
        if self.no_response:
            return
        name = call["params"]["name"]
        value = {"audio_speaker": {"volume": self.volume}, "private_network": "never_return_this"}
        if name == control.VOLUME_TOOL:
            if not self.mismatch:
                self.volume = call["params"]["arguments"]["volume"]
            value = True
            if self.fail_after_set:
                self.no_response = True
        future = self.client.call_results.pop(call["id"])
        future.set_result({"isError": self.set_error and name == control.VOLUME_TOOL,
                           "content": [{"type": "text", "text": json.dumps(value)}]})


def rig():
    client = FakeClient()
    socket = FakeSocket(client)
    bound = asyncio.Event()
    bound.set()
    conn = SimpleNamespace(websocket=socket, mcp_client=client, features={"mcp": True},
                           bind_completed_event=bound, need_bind=False)
    bridge = control.DeviceControl("aa:bb:cc:dd:ee:ff", timeout=0.02)
    bridge.attach(conn, "AA:BB:CC:DD:EE:FF")
    return bridge, conn, socket


def announcement_rig():
    queued = []

    async def sender(conn, text):
        queued.append((conn, text))

    bridge, conn, socket = rig()
    bridge.announcement_sender = sender
    # 生产代码只要求连接已经登记事件循环；离线测试用非空哨兵即可。
    conn.loop = object()
    conn.tts = SimpleNamespace(
        tts_text_queue=asyncio.Queue(), tts_audio_queue=asyncio.Queue()
    )
    conn.client_is_speaking = False
    conn.client_have_voice = False
    conn.calling = False
    return bridge, conn, socket, queued


def test_roundtrip_requires_ack_and_readback_and_reserves_handshake_ids():
    async def run():
        bridge, conn, socket = rig()
        result = await bridge.set_volume(30)
        assert result["verified"] and result["acknowledged"]
        assert result["previous_volume"] == 45 and result["readback_volume"] == 30
        assert [c["id"] for c in socket.calls] == [3, 4, 5]
        assert [c["params"]["name"] for c in socket.calls] == [
            control.STATUS_TOOL, control.VOLUME_TOOL, control.STATUS_TOOL]
        assert "private_network" not in json.dumps(result)
        assert not conn.mcp_client.call_results
    asyncio.run(run())


@pytest.mark.parametrize("value", [True, False, None, "30", 30.5, 0, 4, 61, 100])
def test_rejects_invalid_or_unsafe_volume_without_sending(value):
    async def run():
        bridge, _, socket = rig()
        with pytest.raises(control.ControlError, match="volume_out_of_range"):
            await bridge.set_volume(value)
        assert not socket.calls
    asyncio.run(run())


@pytest.mark.parametrize("change,code", [
    ("offline", "device_offline"), ("unbound", "device_not_ready"),
    ("not_ready", "tools_not_ready"), ("missing", "tool_unavailable"),
    ("ambiguous", "ambiguous_device_connections"), ("schema", "tool_schema_unsupported"),
])
def test_preflight_failures_do_not_send(change, code):
    async def run():
        bridge, conn, socket = rig()
        if change == "offline":
            bridge.detach(conn)
        elif change == "unbound":
            conn.need_bind = True
        elif change == "not_ready":
            conn.mcp_client.ready = False
        elif change == "missing":
            conn.mcp_client.tools.pop("volume")
        elif change == "ambiguous":
            bridge.attach(SimpleNamespace(), bridge.allowed_device_id)
        else:
            conn.mcp_client.tools["volume"]["inputSchema"]["required"].append("other")
        with pytest.raises(control.ControlError, match=code):
            await bridge.set_volume(30)
        assert not socket.calls
    asyncio.run(run())


def test_other_device_is_not_registered_and_status_does_not_send():
    bridge, _, socket = rig()
    bridge.attach(SimpleNamespace(), "00:00:00:00:00:00")
    assert bridge.status()["connection_count"] == 1
    assert bridge.status()["set_volume_supported"]
    assert not socket.calls


@pytest.mark.parametrize("failure", ["no_response", "set_error", "mismatch", "fail_after_set"])
def test_failures_do_not_claim_success_or_retry(failure):
    async def run():
        bridge, conn, socket = rig()
        setattr(socket, failure, True)
        if failure in ("no_response", "set_error"):
            with pytest.raises(control.ControlError):
                await bridge.set_volume(30)
        else:
            result = await bridge.set_volume(30)
            assert result["acknowledged"] and not result["verified"]
        assert len(socket.calls) <= 3
        assert not conn.mcp_client.call_results
    asyncio.run(run())


def test_cancel_cleans_up_pending_call_and_busy_is_rejected():
    async def run():
        bridge, conn, socket = rig()
        socket.no_response = True
        task = asyncio.create_task(bridge.read_volume())
        while not conn.mcp_client.call_results:
            await asyncio.sleep(0)
        with pytest.raises(control.ControlError, match="control_busy"):
            await bridge.set_volume(30)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not conn.mcp_client.call_results and not bridge.operation_lock.locked()
    asyncio.run(run())


@pytest.mark.parametrize("result", [None, {}, {"isError": True},
    {"content": [{"type": "text", "text": "not JSON"}]},
    {"content": [{"type": "image", "text": "true"}]}])
def test_malformed_device_result_is_not_acknowledgement(result):
    with pytest.raises(control.ControlError):
        control.decode_result(result)


def test_tracking_detaches_even_when_original_handler_raises():
    async def run():
        bridge = control.DeviceControl("aa:bb:cc:dd:ee:ff")
        class Connection:
            async def handle_connection(self, ws):
                assert len(bridge.connections) == 1
                raise ValueError("synthetic")
        control.install_connection_tracking(Connection, bridge)
        ws = SimpleNamespace(request=SimpleNamespace(headers={"device-id": bridge.allowed_device_id}))
        with pytest.raises(ValueError):
            await Connection().handle_connection(ws)
        assert not bridge.connections
    asyncio.run(run())


def test_announcement_is_queued_without_claiming_device_acknowledgement():
    async def run():
        bridge, conn, socket, queued = announcement_rig()
        expires = int(time.time() * 1000) + 30_000
        result = await bridge.announce("这是一条主动播报通道测试。", expires)
        assert queued == [(conn, "这是一条主动播报通道测试。")]
        assert result["state"] == "queued"
        assert result["playback_acknowledgement"] == "unavailable"
        assert result["expires_at_ms"] == expires
        assert len(result["operation_id"]) == 32
        assert not socket.calls
    asyncio.run(run())


def test_status_reports_announcement_support_and_current_readiness():
    bridge, conn, _, _ = announcement_rig()
    assert bridge.status()["announcement_supported"] is True
    assert bridge.status()["announcement_ready"] is True
    conn.client_is_speaking = True
    status = bridge.status()
    assert status["announcement_supported"] is True
    assert status["announcement_ready"] is False
    assert status["announcement_reason"] == "device_busy"


@pytest.mark.parametrize("text", ["", " leading", "trailing ", "line\nbreak", "x" * 81])
def test_announcement_rejects_invalid_text(text):
    async def run():
        bridge, _, _, queued = announcement_rig()
        with pytest.raises(control.ControlError, match="invalid_announcement"):
            await bridge.announce(text, int(time.time() * 1000) + 30_000)
        assert not queued
    asyncio.run(run())


@pytest.mark.parametrize("offset,code", [(-1, "announcement_expired"), (301_000, "invalid_expiry")])
def test_announcement_rejects_expired_or_excessive_ttl(offset, code):
    async def run():
        bridge, _, _, queued = announcement_rig()
        with pytest.raises(control.ControlError, match=code):
            await bridge.announce("测试", int(time.time() * 1000) + offset)
        assert not queued
    asyncio.run(run())


@pytest.mark.parametrize("state", ["speaking", "voice", "calling", "text_queue", "audio_queue"])
def test_announcement_never_interrupts_busy_device(state):
    async def run():
        bridge, conn, _, queued = announcement_rig()
        if state == "speaking":
            conn.client_is_speaking = True
        elif state == "voice":
            conn.client_have_voice = True
        elif state == "calling":
            conn.calling = True
        elif state == "text_queue":
            await conn.tts.tts_text_queue.put(object())
        else:
            await conn.tts.tts_audio_queue.put(object())
        with pytest.raises(control.ControlError, match="device_busy"):
            await bridge.announce("测试", int(time.time() * 1000) + 30_000)
        assert not queued
    asyncio.run(run())


def test_real_announcement_sender_reuses_tts_lifecycle_without_chat_history(monkeypatch):
    events = []

    async def send_tts_message(conn, state):
        events.append(("state", state))

    class ContentType:
        ACTION = "ACTION"
        TEXT = "TEXT"

    class SentenceType:
        FIRST = "FIRST"
        LAST = "LAST"

    class DTO:
        def __init__(self, **values):
            self.__dict__.update(values)

    send_module = SimpleNamespace(send_tts_message=send_tts_message)
    dto_module = SimpleNamespace(
        ContentType=ContentType, TTSMessageDTO=DTO, SentenceType=SentenceType
    )
    monkeypatch.setitem(sys.modules, "core.handle.sendAudioHandle", send_module)
    monkeypatch.setitem(sys.modules, "core.providers.tts.dto.dto", dto_module)

    class Queue:
        def put(self, item):
            events.append(("queue", item.sentence_type, item.content_type))

    class TTS:
        tts_text_queue = Queue()

        def store_tts_text(self, sentence_id, text):
            events.append(("store", sentence_id, text))

        def tts_one_sentence(self, conn, content_type, **values):
            events.append(("text", content_type, values["content_detail"], values["sentence_id"]))

    async def run():
        conn = SimpleNamespace(
            client_abort=True, client_is_speaking=False, sentence_id=None, tts=TTS()
        )
        await control.enqueue_announcement(conn, "测试播报")
        assert conn.client_abort is False and conn.client_is_speaking is True
        assert isinstance(conn.sentence_id, str) and len(conn.sentence_id) == 32
        assert events[0] == ("state", "start")
        assert events[1] == ("store", conn.sentence_id, "测试播报")
        assert events[2] == ("queue", "FIRST", "ACTION")
        assert events[3] == ("text", "TEXT", "测试播报", conn.sentence_id)
        assert events[4] == ("queue", "LAST", "ACTION")

    asyncio.run(run())
