"""直连 v2 兼容层的纯离线测试；不启动服务或连接圆屏。"""

import asyncio
import ast
import importlib.util
import json
import subprocess
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


def _fake_sender(monkeypatch, source=protocol):
    """真实v2安装器/编码头，假60ms解码器与socket；不加载音频或模型。"""
    class Connection:
        def _decode_opus_packet(self, payload): return payload
        def _apply_aec(self, timestamp, pcm): return pcm

    original_calls, decoded = [], []
    async def original_send(connection, payload, flow):
        original_calls.append(payload)
        return "original"
    audio = SimpleNamespace(_do_send_audio=original_send)
    handle = SimpleNamespace(sendAudioHandle=audio)
    monkeypatch.setitem(sys.modules, "core", SimpleNamespace(handle=handle))
    monkeypatch.setitem(sys.modules, "core.handle", handle)
    class Decoder:
        def __init__(self, rate, channels):
            assert (rate, channels) == (16000, 1)
        def decode(self, payload, frame_size):
            assert frame_size == 960
            pcm = bytes((payload[0], 0)) * 960
            decoded.append((bytes(payload), pcm))
            return pcm
    monkeypatch.setitem(sys.modules, "opuslib_next", SimpleNamespace(Decoder=Decoder))
    source.install_direct_ws_v2(Connection)
    now = [1000]
    monkeypatch.setattr(source, "time", SimpleNamespace(time=lambda: now[0] / 1000))
    def connection(aec=True):
        conn = Connection()
        conn.headers, conn.conn_from_mqtt_gateway, conn.client_aec = {"Protocol-Version": "2"}, False, aec
        conn.sent = []
        async def send(value): conn.sent.append(value)
        conn.websocket = SimpleNamespace(send=send)
        return conn
    return SimpleNamespace(Connection=Connection, audio=audio, connection=connection,
                           now=now, decoded=decoded, original_calls=original_calls)


def _assert_reference_pairs(conn, payloads):
    packets = [protocol.decode_v2_audio(value) for value in conn.sent if isinstance(value, bytes)]
    assert [payload for _, payload in packets] == payloads
    labels = [label for label, _ in packets]
    assert len(set(labels)) == len(payloads) and all(0 < label < 2**32 for label in labels)
    for label, payload in packets:
        assert conn.aec_audio_cache[label] == bytes((payload[0], 0)) * 960
    return labels


@pytest.mark.parametrize("count", [2, 5])
def test_same_millisecond_preserves_each_wire_packet_reference(monkeypatch, count):
    h = _fake_sender(monkeypatch)
    conn, flow = h.connection(), {}
    payloads = [bytes((i + 1,)) for i in range(count)]
    async def run():
        for payload in payloads:
            await h.audio._do_send_audio(conn, payload, flow)
    asyncio.run(run())
    assert _assert_reference_pairs(conn, payloads) == list(range(1000, 1000 + count))
    assert flow == {"packet_count": count, "sequence": count}
    assert [p for p, _ in h.decoded] == payloads


def test_actual_first_five_prebuffer_sends_do_not_overwrite(monkeypatch):
    h = _fake_sender(monkeypatch)
    # 抽取仓库已保留的固定SDK方法，不复制流控实现，也不导入其依赖。
    root = SCRIPT.parents[3]
    main = root.parents[2] if root.parent.name == "worktrees" else root
    upstream = main / "local/runtime/xiaozhi-esp32-server"
    if not (upstream / ".git").exists():
        pytest.skip("owner-installed pinned SDK unavailable")
    raw = subprocess.check_output(["git", "-C", str(upstream), "show",
        "eb4b28c59ed7ed885258498cf757ce14352d620e:main/xiaozhi-server/core/handle/sendAudioHandle.py"],
        encoding="utf-8")
    method = next(node for node in ast.parse(raw).body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_send_audio_with_rate_control")
    scope = {"PRE_BUFFER_COUNT": 5, "time": SimpleNamespace(time=lambda: 1),
             "_do_send_audio": h.audio._do_send_audio, "asyncio": asyncio}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "pinned:prebuffer", "exec"), scope)
    conn, flow = h.connection(), {"packet_count": 0, "sequence": 0}
    conn.client_abort = False
    payloads = [bytes((i,)) for i in range(1, 6)]
    controller = SimpleNamespace(add_audio=lambda _: pytest.fail("first five must send immediately"))
    asyncio.run(scope["_send_audio_with_rate_control"](conn, payloads, controller, flow, -1))
    assert _assert_reference_pairs(conn, payloads) == [1000, 1001, 1002, 1003, 1004]


@pytest.mark.parametrize("clocks, expected", [
    ([1000, 999, 900, 2000], [1000, 1001, 1002, 2000]),
    ([2**32 - 2, 2**32 - 1, 2**32, 2**32], [2**32 - 2, 2**32 - 1, 1, 2]),
    ([0, 0, 1], [1, 2, 3]),
])
def test_backward_clock_and_wrap_keep_nonzero_forward_labels(monkeypatch, clocks, expected):
    h = _fake_sender(monkeypatch)
    conn, payloads = h.connection(), []
    async def run():
        for i, clock in enumerate(clocks):
            h.now[0] = clock
            payloads.append(bytes((i + 1,)))
            await h.audio._do_send_audio(conn, payloads[-1], {})
    asyncio.run(run())
    assert _assert_reference_pairs(conn, payloads) == expected


def test_wrap_skips_reference_labels_still_in_cache(monkeypatch):
    h = _fake_sender(monkeypatch)
    conn = h.connection()
    async def run():
        h.now[0] = 2**32 - 1
        await h.audio._do_send_audio(conn, b"a", {})
        conn.aec_audio_cache.update({1: b"kept-one", 2: b"kept-two"})
        h.now[0] = 2**32
        await h.audio._do_send_audio(conn, b"b", {})
    asyncio.run(run())
    assert _assert_reference_pairs(conn, [b"a", b"b"]) == [2**32 - 1, 3]
    assert conn.aec_audio_cache[1] == b"kept-one" and conn.aec_audio_cache[2] == b"kept-two"


def test_independent_connections_and_no_aec_still_advance(monkeypatch):
    h = _fake_sender(monkeypatch)
    a, b, no_aec = h.connection(), h.connection(), h.connection(aec=False)
    async def run():
        for conn in (a, b, no_aec):
            await h.audio._do_send_audio(conn, b"a", {})
            await h.audio._do_send_audio(conn, b"b", {})
    asyncio.run(run())
    assert _assert_reference_pairs(a, [b"a", b"b"]) == [1000, 1001]
    assert _assert_reference_pairs(b, [b"a", b"b"]) == [1000, 1001]
    assert a.aec_audio_cache is not b.aec_audio_cache
    assert [protocol.decode_v2_audio(v)[0] for v in no_aec.sent] == [1000, 1001]
    assert not hasattr(no_aec, "aec_audio_cache")


@pytest.mark.parametrize("version,mqtt", [("1", False), ("2", True)])
def test_label_allocator_does_not_change_v1_or_mqtt(monkeypatch, version, mqtt):
    h = _fake_sender(monkeypatch)
    conn = h.connection()
    conn.headers, conn.conn_from_mqtt_gateway = {"Protocol-Version": version}, mqtt
    assert asyncio.run(h.audio._do_send_audio(conn, b"unchanged", {})) == "original"
    assert h.original_calls == [b"unchanged"]
    assert not hasattr(conn, "_longmemory_last_v2_audio_label")


def test_real_output_proxy_stale_epoch_does_not_send_or_reuse_label(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import voice_interruption as guard
    import voice_output_protocol as wire
    h = _fake_sender(monkeypatch)
    conn = h.connection()
    conn.sentence_id = "old"
    conn.session_id = "synthetic"
    conn.tts = SimpleNamespace(_longmemory_cosy_streaming_installed=True)
    conn.config = {"selected_module": {"TTS": "CustomTTS"},
                   "TTS": {"CustomTTS": {"url": "http://127.0.0.1:18770/v1/audio/speech"}}}
    h.Connection._longmemory_tts_wire_installed = True
    h.Connection._longmemory_audio_revocation_installed = True
    h.Connection._longmemory_tts_wire_coverage = staticmethod(lambda: True)

    async def run():
        raw = conn.websocket
        p = wire.OutputProtocol(conn, raw, send_timeout=.5)
        p.proxy = wire.SocketProxy(p)
        conn.websocket = p.proxy
        setattr(conn, wire.ATTRIBUTE, p)
        p.negotiated = p.hello_sent = True
        old = guard.OutputLease(conn, "old")
        await p.gate.acquire()
        async def old_send():
            with p.scope(old, kind="packet"):
                await h.audio._do_send_audio(conn, b"a", {})
        task = asyncio.create_task(old_send())
        await asyncio.sleep(0)  # v2已分配/缓存，在真实代理gate等待。
        assert len(conn.aec_audio_cache) == 1
        old_label = next(iter(conn.aec_audio_cache))
        guard.state_for(conn).revoke("upstream_abort_revoked")
        conn.sentence_id = "new"
        p.gate.release()
        with pytest.raises(wire.StaleOutput):
            await task
        assert not any(isinstance(value, bytes) for value in conn.sent)
        # 本轮不修发送确认事务：拒绝前缓存仍保留，但后包绝不能覆盖它。
        with p.scope(kind="start"):
            await conn.websocket.send(json.dumps({"type": "tts", "state": "start"}))
        fresh = guard.OutputLease(conn, "new")
        with p.scope(fresh, kind="packet"):
            await h.audio._do_send_audio(conn, b"b", {})
        labels = _assert_reference_pairs(conn, [b"b"])
        assert labels[0] != old_label and conn.aec_audio_cache[old_label] == bytes((ord("a"), 0)) * 960
    asyncio.run(run())
