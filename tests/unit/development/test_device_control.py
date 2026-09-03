"""纯离线控制协议测试；模拟圆屏回执，不启动模型或接触真实圆屏。"""

import asyncio
import importlib.util
import json
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
