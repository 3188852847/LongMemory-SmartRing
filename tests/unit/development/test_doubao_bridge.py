"""虚构云事件与内存音频测试，不导入模型、不读取凭据、不连接设备。"""

import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"
sys.path.insert(0, str(SCRIPTS))
from doubao_realtime.bridge import RealtimeBridge
from doubao_realtime.bootstrap import install_realtime_mode, _ConnectionLogger


class Encoder:
    def __init__(self):
        self.buffer = b""
        self.closed = False

    def reset_state(self):
        self.buffer = b""

    def encode_pcm_to_opus_stream(self, pcm, end, callback):
        self.buffer += pcm
        while len(self.buffer) >= 4:
            callback(self.buffer[:4])
            self.buffer = self.buffer[4:]
        if end and self.buffer:
            callback(self.buffer.ljust(4, b"\0"))
            self.buffer = b""

    def close(self):
        self.closed = True


class Client:
    def __init__(self, _config=None):
        self.events_queue = asyncio.Queue()
        self.calls = []
        self.closed = False
        self.upload_gate = None

    async def connect(self):
        self.calls.append("connect")

    async def events(self):
        while True:
            yield await self.events_queue.get()

    async def start_listening(self):
        self.calls.append("start")

    async def stop_listening(self):
        self.calls.append("mute")

    async def commit(self):
        self.calls.append("commit")

    async def send_audio(self, pcm):
        if self.upload_gate is not None:
            await self.upload_gate.wait()
        self.calls.append(pcm)

    async def interrupt(self):
        self.calls.append("cancel")

    async def close(self):
        self.closed = True


class Connection:
    def __init__(self):
        self.sent = []
        self.states = []
        self.packets = []
        self.client_is_speaking = False
        self.client_have_voice = False
        self.client_abort = False
        self.client_listen_mode = "auto"
        self.session_id = "synthetic-session"
        self.sentence_id = None
        self.websocket = SimpleNamespace(send=self.send, close=self.close)
        self.config = {"Memory": {"LongMemory": {"allowed_device_id": "aa:bb:cc:dd:ee:ff"}}}
        self.device_id = "aa:bb:cc:dd:ee:ff"
        self.bind_completed_event = asyncio.Event()
        self.need_bind = False
        self.conn_from_mqtt_gateway = False
        self.client_aec = False
        self.logger = SimpleNamespace(bind=lambda **_: SimpleNamespace(error=lambda _: None))
        self.routed = []
        self.closed = False

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def reset_audio_states(self):
        self.client_have_voice = False

    async def _initialize_private_config_async(self):
        self.bind_completed_event.set()

    async def _route_message(self, message):
        self.routed.append(message)

    def _decode_opus_packet(self, packet):
        return b"\1\0" * 4 if packet == b"opus" else None

    def clear_queues(self):
        pass

    async def close(self, ws=None):
        self.closed = True


async def audio_sender(connection, packet):
    connection.packets.append(packet)


async def state_sender(connection, state, text=None):
    connection.states.append((state, text))


def rig(**kwargs):
    connection, client, encoder = Connection(), Client(), Encoder()
    bridge = RealtimeBridge(connection, client, encoder, audio_sender=audio_sender,
                            state_sender=state_sender, **kwargs)
    return bridge, connection, client, encoder


def event(kind, response_id="", **kwargs):
    return SimpleNamespace(kind=kind, response_id=response_id, **kwargs)


def test_input_order_partial_is_not_saved_and_output_flushes_only_at_end():
    async def run():
        bridge, conn, client, encoder = rig()
        await bridge.start()
        try:
            await bridge.listen("start", "realtime")
            await bridge.accept_pcm(b"\1\0" * 4)
            await bridge.listen("stop")
            await asyncio.wait_for(bridge.input_queue.join(), 1)
            assert client.calls == ["connect", "start", b"\1\0" * 4, "commit", "mute"]
            await bridge.handle_event(event("transcript", text="虚构半句", is_final=False))
            assert not conn.sent
            await bridge.handle_event(event("transcript", text="合成测试", is_final=True))
            assert conn.sent == [{"type": "stt", "text": "合成测试", "session_id": "synthetic-session"}]
            await bridge.handle_event(event("response_started", "r1"))
            await bridge.handle_event(event("audio", "r1", audio=b"\2\0" * 3))
            await asyncio.wait_for(bridge.output_queue.join(), 1)
            assert conn.packets == [b"\2\0" * 2]
            await bridge.handle_event(event("response_done", "r1"))
            await asyncio.wait_for(bridge.output_queue.join(), 1)
            assert conn.packets == [b"\2\0" * 2, b"\2\0\0\0"]
            assert conn.states == [("start", None), ("stop", None)]
            assert not conn.client_is_speaking
            assert bridge.snapshot()["memory_enabled"] is False
            conn.client_have_voice = True
            await bridge.handle_event(event("transcript", text="", is_final=True))
            assert not conn.client_have_voice
        finally:
            await bridge.close()
        assert encoder.closed and client.closed
        assert not bridge._tasks
    asyncio.run(run())


def test_cancel_replaces_queue_and_cannot_resurrect_old_or_unknown_response():
    async def run():
        bridge, conn, client, _ = rig()
        blocked = asyncio.Event()
        async def blocked_audio(connection, packet):
            if packet == b"old!":
                blocked.set()
                await asyncio.Event().wait()
            connection.packets.append(packet)
        bridge.audio_sender = blocked_audio
        await bridge.start()
        try:
            await bridge.handle_event(event("response_started", "old"))
            await bridge.handle_event(event("audio", "old", audio=b"old!more"))
            await asyncio.wait_for(blocked.wait(), 1)
            old_queue = bridge.output_queue
            await bridge.interrupt()
            assert bridge.output_queue is not old_queue
            await bridge.handle_event(event("response_started", "unknown-after-cancel"))
            assert bridge.response_id is None
            await bridge.handle_event(event("speech_started"))
            await bridge.handle_event(event("response_started", "new"))
            await bridge.handle_event(event("audio", "old", audio=b"late"))
            await bridge.handle_event(event("response_done", "old"))
            await bridge.handle_event(event("audio", "new", audio=b"new!"))
            await bridge.handle_event(event("response_done", "new"))
            await asyncio.wait_for(bridge.output_queue.join(), 1)
            assert conn.packets == [b"new!"]
            assert "cancel" in client.calls
        finally:
            await bridge.close()
    asyncio.run(run())


def test_normal_following_response_does_not_cut_previous_tail():
    async def run():
        bridge, conn, _, _ = rig()
        await bridge.start()
        try:
            for rid, pcm in (("r1", b"one!"), ("r2", b"two!")):
                await bridge.handle_event(event("response_started", rid))
                await bridge.handle_event(event("audio", rid, audio=pcm))
                await bridge.handle_event(event("response_done", rid))
            await asyncio.wait_for(bridge.output_queue.join(), 1)
            assert conn.packets == [b"one!", b"two!"]
            assert conn.states == [("start", None), ("stop", None)] * 2
        finally:
            await bridge.close()
    asyncio.run(run())


def test_stop_is_ordered_without_blocking_device_abort_route():
    async def run():
        bridge, _, client, _ = rig()
        client.upload_gate = asyncio.Event()
        await bridge.start()
        try:
            await bridge.listen("start")
            await bridge.accept_pcm(b"\0\0")
            await asyncio.wait_for(bridge.listen("stop"), 0.1)
            await asyncio.wait_for(bridge.interrupt(), 0.1)
            assert "cancel" in client.calls and "commit" not in client.calls
            client.upload_gate.set()
            await asyncio.wait_for(bridge.input_queue.join(), 1)
            assert client.calls.index(b"\0\0") < client.calls.index("commit") < client.calls.index("mute")
        finally:
            await bridge.close()
    asyncio.run(run())


def test_rate_controller_backpressure_and_cancel_are_bounded():
    async def run():
        bridge, conn, _, _ = rig()
        conn.audio_rate_controller = SimpleNamespace(queue=[b"pending"] * 32, reset=lambda: None)
        await bridge.start()
        try:
            await bridge.handle_event(event("response_started", "r1"))
            await bridge.handle_event(event("audio", "r1", audio=b"held"))
            await asyncio.sleep(0.04)
            assert conn.packets == []
            await asyncio.wait_for(bridge.interrupt(), 0.2)
            assert conn.packets == []
        finally:
            await bridge.close()
    asyncio.run(run())


def test_malformed_audio_and_queue_overflow_fail_closed_without_content():
    async def run():
        bridge, conn, client, encoder = rig(queue_limit=1)
        await bridge.start()
        await bridge.handle_event(event("response_started", "r"))
        await bridge.handle_event(event("audio", "r", audio=b"odd"))
        assert bridge.snapshot()["failure_code"] == "realtime_audio_invalid"
        assert not bridge.ready and client.closed and encoder.closed
        assert "odd" not in str(bridge.snapshot())
        second, _, second_client, _ = rig(queue_limit=1)
        second.ready, second.listening = True, True
        await second.accept_pcm(b"\0\0")
        await second.accept_pcm(b"\0\0")
        assert second.failure_code == "realtime_input_overflow"
        assert second_client.closed
    asyncio.run(run())


def test_cloud_events_task_and_close_release_all_workers():
    async def run():
        bridge, conn, client, encoder = rig()
        await bridge.start()
        await client.events_queue.put(event("error", text="private-cloud-body"))
        for _ in range(20):
            if bridge._closed:
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await bridge.close()
        assert bridge.failure_code == "realtime_cloud_error"
        assert encoder.closed and client.closed
        assert conn.closed
        assert not [task for task in bridge._tasks if not task.done()]
    asyncio.run(run())


def test_ambiguous_turn_fails_closed_and_preserves_only_fixed_reason():
    async def run():
        bridge, conn, _, _ = rig()
        await bridge.start()
        await bridge.handle_event(event("error", code="realtime_turn_ambiguous", text="private"))
        assert bridge.failure_code == "realtime_turn_ambiguous"
        assert conn.closed and not bridge.ready
        assert "private" not in str(bridge.snapshot())
    asyncio.run(run())


def test_pcm_backlog_budget_and_failed_cancel_disconnect_device():
    async def run():
        bridge, conn, _, _ = rig()
        await bridge.start()
        await bridge.handle_event(event("response_started", "r"))
        await bridge.handle_event(event("audio", "r", audio=b"\0\0" * 120001))
        for _ in range(30):
            await asyncio.sleep(0)
            if conn.closed:
                break
        await bridge.close()
        assert bridge.failure_code == "realtime_output_overflow"
        assert conn.closed and conn.packets == []
        second, device, client, _ = rig()
        async def fail_cancel():
            raise ValueError("private cancel response")
        client.interrupt = fail_cancel
        await second.start()
        await second.interrupt()
        assert second.failure_code == "realtime_cancel_failed"
        assert device.closed and not second.ready
    asyncio.run(run())


def test_connection_log_never_records_authorization_header():
    logged = []
    logger = _ConnectionLogger(SimpleNamespace(info=lambda message: logged.append(message)))
    logger.info("127.0.0.1 conn - Headers: {'Authorization': 'secret'}")
    assert logged == ["圆屏连接已建立；握手头不记录"]


def test_bootstrap_skips_shared_models_and_routes_hello_pcm_and_close(monkeypatch):
    async def run():
        server_module = SimpleNamespace(initialize_modules=lambda *_: pytest.fail("local model loaded"))
        monkeypatch.setitem(sys.modules, "core", SimpleNamespace(websocket_server=server_module))
        monkeypatch.setitem(sys.modules, "core.handle.sendAudioHandle",
                            SimpleNamespace(sendAudio=audio_sender, send_tts_message=state_sender))
        class CurrentConnection(Connection):
            pass
        install_realtime_mode(CurrentConnection, object(), client_factory=Client, encoder_factory=Encoder)
        assert server_module.initialize_modules(None, None, True, True, True) == {}
        conn = CurrentConnection()
        await conn._background_initialize()
        assert conn.asr is conn.tts is conn.llm is conn.memory is None
        try:
            await conn._route_message(json.dumps({"type": "hello", "features": {"mcp": True, "aec": True},
                "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
            hello = json.loads(conn.routed[-1])
            assert hello["features"] == {"mcp": True, "aec": True}
            assert hello["audio_params"]["sample_rate"] == 24000
            await conn._route_message(json.dumps({"type": "listen", "state": "start"}))
            await conn._route_message(b"opus")
            await asyncio.wait_for(conn._doubao_bridge.input_queue.join(), 1)
            assert b"\1\0" * 4 in conn._doubao_bridge.client.calls
            await conn._route_message(json.dumps({"type": "abort"}))
            assert "cancel" in conn._doubao_bridge.client.calls
        finally:
            await conn._save_and_close(None)
        assert conn.closed and conn._doubao_bridge.client.closed
    asyncio.run(run())


def test_bootstrap_cloud_failure_closes_device_and_unrecognized_device_never_connects(monkeypatch):
    async def run():
        monkeypatch.setitem(sys.modules, "core", SimpleNamespace(websocket_server=SimpleNamespace()))
        monkeypatch.setitem(sys.modules, "core.handle.sendAudioHandle",
                            SimpleNamespace(sendAudio=audio_sender, send_tts_message=state_sender))
        calls = []
        class BrokenClient(Client):
            async def connect(self):
                calls.append("connect")
                raise ValueError("private-cloud-content")
        class CurrentConnection(Connection):
            pass
        install_realtime_mode(CurrentConnection, object(), client_factory=BrokenClient, encoder_factory=Encoder)
        conn = CurrentConnection()
        await conn._background_initialize()
        assert conn.closed and conn._doubao_failure_code == "realtime_initialization_failed"
        assert conn._doubao_bridge.client.closed
        rejected = CurrentConnection()
        rejected.device_id = "00:00:00:00:00:00"
        await rejected._background_initialize()
        assert rejected.closed
        assert calls == ["connect"]
    asyncio.run(run())
