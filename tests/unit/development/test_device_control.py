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


def round_skin(skin_id="rose-night-v1"):
    return {
        "skin_api": 1, "skin_id": skin_id, "manifest_sha256": "a" * 64,
        "background": 0x171B26, "foreground": 0xF7F4F8, "muted": 0xCBD1DC,
        "accent": 0xDF72A8, "listening": 0x69D5FF, "thinking": 0xF7C65A,
        "happy": 0x7DE2B8, "concerned": 0x8AA8FF, "error": 0xF16C73,
        "eye_width": 22, "eye_height": 36, "mouth_width": 38,
    }


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
            "brightness": {"name": control.BRIGHTNESS_TOOL, "inputSchema": {
                "type": "object", "properties": {"brightness": {
                    "type": "integer", "minimum": 0, "maximum": 100}}, "required": ["brightness"]}},
            "theme": {"name": control.THEME_TOOL, "inputSchema": {
                "type": "object", "properties": {"theme": {"type": "string"}}, "required": ["theme"]}},
            "deactivate_wallpaper": {
                "name": control.DEACTIVATE_ROUND_WALLPAPER_TOOL,
                "inputSchema": {"type": "object"},
            },
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
        self.brightness = 45
        self.theme = "light"
        self.round_skin = round_skin()
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
        value = {"audio_speaker": {"volume": self.volume},
                 "screen":{"brightness":self.brightness,"theme":self.theme},
                 "battery":{"level":72,"charging":True},
                 "network":{"ssid":"private","signal":"strong"},
                 "chip":{"temperature":41.25}, "private_network": "never_return_this"}
        if name == control.VOLUME_TOOL:
            if not self.mismatch:
                self.volume = call["params"]["arguments"]["volume"]
            value = True
            if self.fail_after_set:
                self.no_response = True
        elif name == control.BRIGHTNESS_TOOL:
            self.brightness = call["params"]["arguments"]["brightness"]
            value = True
        elif name == control.THEME_TOOL:
            self.theme = call["params"]["arguments"]["theme"]
            value = True
        elif name == control.GET_ROUND_SKIN_TOOL:
            value = self.round_skin
        elif name == control.SET_ROUND_SKIN_TOOL:
            self.round_skin = call["params"]["arguments"]
            value = True
        elif name == control.STAGE_ROUND_WALLPAPER_TOOL:
            arguments = call["params"]["arguments"]
            value = {
                "wallpaper_api": 1, "slot": "b",
                "wallpaper_id": arguments["wallpaper_id"],
                "sha256": arguments["sha256"],
                "size_bytes": arguments["size_bytes"],
                "state": "staged_verified",
            }
        elif name == control.GET_ROUND_WALLPAPER_TOOL:
            value = {
                "wallpaper_api": 1, "active_valid": True, "active_slot": "a",
                "active_wallpaper_id": "wallpaper-" + "a" * 20,
                "active_sha256": "b" * 64, "active_size_bytes": 2321851,
                "rollback_available": True,
            }
        elif name == control.ACTIVATE_ROUND_WALLPAPER_TOOL:
            arguments = call["params"]["arguments"]
            value = {**arguments, "state": "activation_pending_restart"}
        elif name == control.ROLLBACK_ROUND_WALLPAPER_TOOL:
            value = {
                "wallpaper_api": 1, "slot": "a",
                "wallpaper_id": "wallpaper-" + "a" * 20,
                "sha256": "b" * 64, "size_bytes": 2321851,
                "state": "rollback_pending_restart",
            }
        elif name == control.DEACTIVATE_ROUND_WALLPAPER_TOOL:
            value = {
                "wallpaper_api": 1, "slot": "a",
                "wallpaper_id": "wallpaper-" + "a" * 20,
                "sha256": "b" * 64, "size_bytes": 2321851,
                "state": "deactivation_pending_restart",
            }
        elif name == control.REBOOT_TOOL:
            value = True
        future = self.client.call_results.pop(call["id"])
        future.set_result({"isError": self.set_error and name == control.VOLUME_TOOL,
                           "content": [{"type": "text", "text": json.dumps(value)}]})


def rig():
    client = FakeClient()
    socket = FakeSocket(client)
    bound = asyncio.Event()
    bound.set()
    conn = SimpleNamespace(websocket=socket, mcp_client=client, features={"mcp": True, "aec": True},
                           bind_completed_event=bound, need_bind=False)
    bridge = control.DeviceControl("aa:bb:cc:dd:ee:ff", timeout=0.02)
    bridge.attach(conn, "AA:BB:CC:DD:EE:FF")
    return bridge, conn, socket


def test_realtime_control_can_stop_without_tts_and_never_advertises_announcements():
    async def run():
        controller, conn, socket = rig()
        cancelled = []
        async def interrupt():
            cancelled.append(True)
        conn.voice_mode = "doubao_realtime"
        conn.tts = None
        conn.client_is_speaking = True
        conn._doubao_bridge = SimpleNamespace(
            ready=True, response_id="synthetic-response", interrupt=interrupt,
            snapshot=lambda: {"ready": True, "memory_enabled": False},
        )
        status = controller.status()
        assert status["voice_mode"] == "doubao_realtime"
        assert status["stop_speech_supported"] is True
        assert status["announcement_supported"] is False
        assert status["announcement_ready"] is False
        result = await controller.stop_speech()
        assert result["server_interrupted"] is True
        assert cancelled == [True]
        assert not socket.calls
    asyncio.run(run())


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


def test_status_projection_and_screen_controls_are_verified_without_ssid():
    async def run():
        bridge, _, _ = rig()
        status = await bridge.read_status()
        assert status == {"volume":45,"brightness":45,"theme":"light",
                          "battery":{"level":72,"charging":True},
                          "network":{"signal":"strong"},"chip":{"temperature":41.2}}
        assert (await bridge.set_brightness(70))["verified"] is True
        assert (await bridge.set_theme("dark"))["verified"] is True
        cached = bridge.status()
        assert cached["set_brightness_supported"] and cached["set_theme_supported"]
    asyncio.run(run())


def test_round_skin_uses_hidden_fixed_tools_and_requires_exact_readback():
    async def run():
        bridge, conn, socket = rig()
        wanted = round_skin("mint-calm-v1")
        wanted["manifest_sha256"] = "b" * 64
        result = await bridge.set_round_skin(wanted)
        assert result["verified"] is True
        assert result["device_skin"] == wanted
        assert [call["params"]["name"] for call in socket.calls] == [
            control.SET_ROUND_SKIN_TOOL, control.GET_ROUND_SKIN_TOOL,
        ]
        assert control.GET_ROUND_SKIN_TOOL not in {
            item["name"] for item in conn.mcp_client.tools.values()
        }
        assert await bridge.read_round_skin() == wanted
    asyncio.run(run())


def test_round_skin_rejects_open_fields_before_sending():
    async def run():
        bridge, _, socket = rig()
        invalid = {**round_skin(), "script": "unknown"}
        with pytest.raises(control.ControlError, match="round_skin_invalid"):
            await bridge.set_round_skin(invalid)
        assert not socket.calls
    asyncio.run(run())


def test_round_wallpaper_stages_only_to_hidden_fixed_tool_with_exact_readback():
    async def run():
        bridge, conn, socket = rig()
        result = await bridge.stage_round_wallpaper(
            item_id="wallpaper-" + "a" * 20,
            sha256="b" * 64,
            size_bytes=2321851,
            url="http://192.168.124.93:8768/wallpaper/" + "c" * 64,
        )
        assert result["state"] == "staged_verified"
        assert result["slot"] == "b"
        assert result["sha256"] == "b" * 64
        assert socket.calls[-1]["params"]["name"] == control.STAGE_ROUND_WALLPAPER_TOOL
        assert control.STAGE_ROUND_WALLPAPER_TOOL not in {
            item["name"] for item in conn.mcp_client.tools.values()
        }

    asyncio.run(run())


def test_round_wallpaper_activation_and_rollback_use_fixed_tools_then_reboot():
    async def run():
        bridge, _, socket = rig()
        staged = {
            "wallpaper_api": 1, "slot": "b",
            "wallpaper_id": "wallpaper-" + "a" * 20,
            "sha256": "b" * 64, "size_bytes": 2321851,
            "state": "staged_verified",
        }
        activated = await bridge.activate_round_wallpaper(staged)
        assert activated["state"] == "activated_restarting"
        assert [call["params"]["name"] for call in socket.calls[-2:]] == [
            control.ACTIVATE_ROUND_WALLPAPER_TOOL, control.REBOOT_TOOL,
        ]
        rolled_back = await bridge.rollback_round_wallpaper()
        assert rolled_back["state"] == "rollback_restarting"
        assert [call["params"]["name"] for call in socket.calls[-2:]] == [
            control.ROLLBACK_ROUND_WALLPAPER_TOOL, control.REBOOT_TOOL,
        ]

        deactivated = await bridge.deactivate_round_wallpaper()
        assert deactivated["state"] == "skin_mode_restarting"
        assert [call["params"]["name"] for call in socket.calls[-2:]] == [
            control.DEACTIVATE_ROUND_WALLPAPER_TOOL, control.REBOOT_TOOL,
        ]

    asyncio.run(run())


def test_round_wallpaper_activation_reconciles_ambiguous_reboot_without_retry(monkeypatch):
    async def run():
        bridge, connection, socket = rig()
        staged = {
            "wallpaper_api": 1, "slot": "b",
            "wallpaper_id": "wallpaper-" + "a" * 20,
            "sha256": "b" * 64, "size_bytes": 2321851,
            "state": "staged_verified",
        }
        original_call = bridge._call
        reconciled = []

        async def call(conn, name, arguments, timeout=None):
            if name == control.REBOOT_TOOL:
                raise control.ControlError("device_timeout_outcome_unknown", 504)
            return await original_call(conn, name, arguments, timeout=timeout)

        async def confirm(selected, previous_connection):
            reconciled.append((selected, previous_connection))

        monkeypatch.setattr(bridge, "_call", call)
        monkeypatch.setattr(bridge, "_confirm_round_wallpaper_after_restart", confirm)

        result = await bridge.activate_round_wallpaper(staged)
        assert result["state"] == "activated_restarting"
        assert reconciled == [({**staged, "state": "activation_pending_restart"}, connection)]
        # 不确定意味着设备可能已经执行重启，因此绝不能自动发第二次 reboot。
        assert [item["params"]["name"] for item in socket.calls] == [
            control.ACTIVATE_ROUND_WALLPAPER_TOOL,
        ]

    asyncio.run(run())


def test_skin_mode_returns_restarting_when_reboot_reply_is_lost(monkeypatch):
    async def run():
        bridge, _, socket = rig()
        original_call = bridge._call

        async def call(conn, name, arguments, timeout=None):
            if name == control.REBOOT_TOOL:
                raise control.ControlError("device_connection_changed", 502)
            return await original_call(conn, name, arguments, timeout=timeout)

        monkeypatch.setattr(bridge, "_call", call)
        result = await bridge.deactivate_round_wallpaper()

        assert result["state"] == "skin_mode_restarting"
        assert [item["params"]["name"] for item in socket.calls] == [
            control.DEACTIVATE_ROUND_WALLPAPER_TOOL,
        ]

    asyncio.run(run())


def test_round_wallpaper_restart_confirmation_requires_exact_new_connection_readback():
    async def run():
        bridge, previous_connection, _ = rig()
        _, current_connection, current_socket = rig()
        bridge.detach(previous_connection)
        bridge.attach(current_connection, bridge.allowed_device_id)
        selected = {
            "wallpaper_api": 1, "slot": "a",
            "wallpaper_id": "wallpaper-" + "a" * 20,
            "sha256": "b" * 64, "size_bytes": 2321851,
            "state": "activation_pending_restart",
        }

        status = await bridge._confirm_round_wallpaper_after_restart(
            selected, previous_connection,
        )
        assert status["active_valid"] is True
        assert current_socket.calls[-1]["params"]["name"] == control.GET_ROUND_WALLPAPER_TOOL

        with pytest.raises(control.ControlError, match="round_wallpaper_readback_mismatch"):
            await bridge._confirm_round_wallpaper_after_restart(
                {**selected, "slot": "b"}, previous_connection,
            )

    asyncio.run(run())


def test_round_wallpaper_status_uses_hidden_fixed_tool_and_exact_projection():
    async def run():
        bridge, conn, socket = rig()
        status = await bridge.read_round_wallpaper()
        assert status["active_valid"] is True and status["rollback_available"] is True
        assert socket.calls[-1]["params"]["name"] == control.GET_ROUND_WALLPAPER_TOOL
        assert control.GET_ROUND_WALLPAPER_TOOL not in {
            item["name"] for item in conn.mcp_client.tools.values()
        }

    asyncio.run(run())


@pytest.mark.parametrize("change", [
    {"item_id": "../wallpaper"}, {"sha256": "bad"}, {"size_bytes": 0},
    {"url": "https://192.168.124.93:8768/wallpaper/" + "c" * 64},
    {"url": "http://8.8.8.8:8768/wallpaper/" + "c" * 64},
    {"url": "http://192.168.124.93:8768/other/" + "c" * 64},
])
def test_round_wallpaper_rejects_unscoped_delivery_before_sending(change):
    async def run():
        bridge, _, socket = rig()
        values = {
            "item_id": "wallpaper-" + "a" * 20, "sha256": "b" * 64,
            "size_bytes": 2321851,
            "url": "http://192.168.124.93:8768/wallpaper/" + "c" * 64,
        }
        values.update(change)
        with pytest.raises(control.ControlError, match="round_wallpaper_stage_invalid"):
            await bridge.stage_round_wallpaper(**values)
        assert not socket.calls

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
    assert bridge.status()["aec_advertised"] is True
    assert bridge.status()["natural_interruption"] == {
        "version": 1, "state": "blocked", "device_aec_advertised": True,
        "server_aec_active": False, "timestamped_audio_supported": False,
        "listen_mode": "unknown", "reason": "timestamp_transport_unavailable",
    }
    assert bridge.status()["set_volume_supported"]
    assert not socket.calls


def test_natural_interruption_requires_all_observed_transport_conditions():
    bridge, conn, _ = rig()
    conn.client_aec = True
    conn.conn_from_mqtt_gateway = True
    conn.client_listen_mode = "realtime"
    diagnostic = bridge.status()["natural_interruption"]
    assert diagnostic == {
        "version": 1, "state": "trial_ready", "device_aec_advertised": True,
        "server_aec_active": True, "timestamped_audio_supported": True,
        "listen_mode": "realtime", "reason": "ready_for_controlled_trial",
    }


def test_direct_websocket_v2_counts_only_when_compatibility_wrapper_is_installed():
    bridge, conn, _ = rig()
    conn.client_aec = True
    conn.client_listen_mode = "realtime"
    conn.headers = {"Protocol-Version": "2"}
    assert bridge.status()["natural_interruption"]["reason"] == "timestamp_transport_unavailable"
    conn._longmemory_direct_ws_v2_installed = True
    assert bridge.status()["natural_interruption"]["state"] == "trial_ready"


def test_natural_interruption_offline_is_explicitly_unavailable():
    bridge, conn, _ = rig()
    bridge.detach(conn)
    assert bridge.status()["natural_interruption"]["reason"] == "device_offline"


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
    assert bridge.status()["stop_speech_supported"] is True
    assert bridge.status()["announcement_ready"] is True
    assert bridge.status()["user_session_active"] is False
    conn.client_is_speaking = True
    status = bridge.status()
    assert status["announcement_supported"] is True
    assert status["announcement_ready"] is False
    assert status["user_session_active"] is True
    assert status["announcement_reason"] == "device_busy"


def test_stop_speech_interrupts_server_and_reports_missing_device_ack():
    async def run():
        bridge, conn, socket, _ = announcement_rig()
        stopped = []

        async def aborter(selected):
            stopped.append(selected)
            selected.client_abort = True
            while not selected.tts.tts_text_queue.empty():
                selected.tts.tts_text_queue.get_nowait()
            selected.client_is_speaking = False

        bridge.response_aborter = aborter
        conn.client_is_speaking = True
        await conn.tts.tts_text_queue.put("synthetic answer")
        result = await bridge.stop_speech()

        assert stopped == [conn]
        assert result["state"] == "stop_sent"
        assert result["server_interrupted"] is True
        assert result["device_acknowledgement"] == "unavailable"
        assert len(result["operation_id"]) == 32
        assert conn.client_abort is True
        assert conn.tts.tts_text_queue.empty()
        assert not socket.calls  # 不借道 MCP 任意工具。

    asyncio.run(run())


def test_stop_speech_is_noop_when_already_idle():
    async def run():
        bridge, _, _, _ = announcement_rig()
        called = []

        async def aborter(conn):
            called.append(conn)

        bridge.response_aborter = aborter
        result = await bridge.stop_speech()
        assert result["state"] == "already_idle"
        assert result["server_interrupted"] is False
        assert result["device_acknowledgement"] == "not_requested"
        assert called == []

    asyncio.run(run())


def test_status_exposes_only_tracker_voice_latency_snapshot():
    bridge, conn, _, _ = announcement_rig()
    snapshot = {
        "version": 1,
        "state": "audio_ready",
        "started_at": "2026-09-10T10:20:30+00:00",
        "tts_backend": "edge",
        "timings_ms": {
            "memory_ready_ms": 9,
            "llm_requested_ms": 10,
            "llm_first_output_ms": 140,
            "tts_started_ms": 190,
            "audio_ready_ms": 520,
            "first_audio_sent_ms": None,
            "response_completed_ms": 400,
        },
    }
    conn._longmemory_voice_latency = SimpleNamespace(snapshot=lambda: snapshot)
    assert bridge.status()["voice_latency"] == snapshot


def test_last_voice_latency_remains_visible_after_device_disconnects():
    bridge, conn, _, _ = announcement_rig()
    snapshot = {
        "version": 1,
        "state": "first_audio_sent",
        "started_at": "2026-09-12T13:30:00+00:00",
        "tts_backend": "sanotts",
        "timings_ms": {
            "memory_ready_ms": 20,
            "llm_requested_ms": 30,
            "llm_first_output_ms": 230,
            "tts_started_ms": 260,
            "audio_ready_ms": 760,
            "first_audio_sent_ms": 790,
            "response_completed_ms": 400,
        },
    }
    conn._longmemory_voice_latency = SimpleNamespace(snapshot=lambda: snapshot)

    bridge.detach(conn)

    status = bridge.status()
    assert status["ready"] is False
    assert status["reason"] == "device_offline"
    assert status["voice_latency"] == snapshot


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
