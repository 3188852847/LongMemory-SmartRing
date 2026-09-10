"""直连 v2 兼容层的纯离线测试；不启动服务或连接圆屏。"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/direct_ws_v2.py"
SPEC = importlib.util.spec_from_file_location("direct_ws_v2_tested", SCRIPT)
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


def test_v2_binary_roundtrip_and_network_byte_order():
    packet = protocol.encode_v2_audio(b"opus", 0x01020304)
    assert packet[:16] == bytes.fromhex("00020000000000000102030400000004")
    assert protocol.decode_v2_audio(packet) == (0x01020304, b"opus")


@pytest.mark.parametrize("message", [
    b"", b"short",
    bytes.fromhex("00010000000000000000000100000001") + b"x",
    bytes.fromhex("00020001000000000000000100000001") + b"x",
    bytes.fromhex("00020000000000000000000100000002") + b"x",
])
def test_v2_decoder_rejects_malformed_or_mismatched_packets(message):
    with pytest.raises(ValueError, match="invalid_v2_audio"):
        protocol.decode_v2_audio(message)


def test_protocol_version_header_is_case_insensitive_and_conservative():
    assert protocol.connection_protocol_version(SimpleNamespace(headers={"Protocol-Version": "2"})) == 2
    assert protocol.connection_protocol_version(SimpleNamespace(headers={"protocol-version": "bad"})) == 1
    assert protocol.connection_protocol_version(SimpleNamespace(headers=None)) == 1


def test_installer_preserves_v1_and_decodes_v2_with_aec(monkeypatch):
    calls = []

    class Logger:
        def bind(self, **_kwargs): return self
        def warning(self, message): calls.append(("warning", message))

    class Connection:
        def _decode_opus_packet(self, payload):
            calls.append(("decode", payload))
            return b"pcm"
        def _apply_aec(self, timestamp, pcm):
            calls.append(("aec", timestamp, pcm))
            return b"clean"

    async def original_send(connection, payload, flow):
        calls.append(("original_send", payload))
        return "original"

    audio_module = SimpleNamespace(_do_send_audio=original_send)
    core_handle = SimpleNamespace(sendAudioHandle=audio_module)
    monkeypatch.setitem(sys.modules, "core", SimpleNamespace(handle=core_handle))
    monkeypatch.setitem(sys.modules, "core.handle", core_handle)
    class Decoder:
        def __init__(self, sample_rate, channels):
            calls.append(("decoder", sample_rate, channels))
        def decode(self, payload, frame_size):
            calls.append(("reference", payload, frame_size))
            return b"reference-pcm"
    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(Decoder=Decoder))
    protocol.install_direct_ws_v2(Connection)

    v1 = Connection()
    v1.headers, v1.conn_from_mqtt_gateway = {"Protocol-Version": "1"}, False
    assert v1._decode_opus_packet(b"raw") == b"pcm"

    v2 = Connection()
    v2.headers = {"Protocol-Version": "2"}
    v2.conn_from_mqtt_gateway = False
    v2.client_aec = True
    v2.logger = Logger()
    assert v2._decode_opus_packet(protocol.encode_v2_audio(b"opus", 42)) == b"clean"
    assert ("aec", 42, b"pcm") in calls
    assert v2._decode_opus_packet(b"bad") is None

    v1.websocket = SimpleNamespace(send=None)
    assert asyncio.run(audio_module._do_send_audio(v1, b"out", {})) == "original"

    sent = []
    async def websocket_send(message): sent.append(message)
    v2.websocket = SimpleNamespace(send=websocket_send)
    flow = {"packet_count": 3, "sequence": 7}
    asyncio.run(audio_module._do_send_audio(v2, b"out", flow))
    timestamp, payload = protocol.decode_v2_audio(sent[0])
    assert timestamp > 0 and payload == b"out"
    assert flow == {"packet_count": 4, "sequence": 8}
    assert v2.aec_audio_cache[timestamp] == b"reference-pcm"
