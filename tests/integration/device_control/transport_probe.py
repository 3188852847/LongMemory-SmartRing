"""在小智 Python 3.10 中运行的合成传输测试，不导入 app/模型、不连接圆屏。

加载固定上游 MCP 客户端和回执解析代码，只替换日志/工具名/鉴权辅助依赖。
用模拟 WebSocket 回执驱动真实 MCP Future，再从独立 CLI 进程经过 HTTP 调用。
"""

import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import types

from aiohttp import ClientSession, web


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"
UPSTREAM = Path(sys.argv[1])
sys.path.insert(0, str(SCRIPTS))
from device_control import DeviceControl, STATUS_TOOL, VOLUME_TOOL
from control_http import create_app, ensure_token


def load_upstream(relative, module_name):
    spec = importlib.util.spec_from_file_location(module_name, UPSTREAM / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuietLog:
    def bind(self, **kwargs):
        return self

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


for name, attributes in {
    "core.utils.util": {"sanitize_tool_name": lambda name: name.replace(".", "_"),
                        "get_vision_url": lambda config: "unused"},
    "core.utils.auth": {"AuthToken": object},
    "config.logger": {"setup_logging": lambda: QuietLog()},
}.items():
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module

client_module = load_upstream("core/providers/tools/device_mcp/mcp_client.py", "probe_mcp_client")
handler_module = load_upstream("core/providers/tools/device_mcp/mcp_handler.py", "probe_mcp_handler")


class Device:
    def __init__(self):
        self.mcp_client = client_module.MCPClient()
        self.features = {"mcp": True}
        self.bind_completed_event = asyncio.Event()
        self.bind_completed_event.set()
        self.need_bind = False
        self.websocket = self
        self.state = types.SimpleNamespace(name="OPEN")
        self.func_handler = None
        self.volume = 40
        self.sent = []

    async def send(self, message):
        payload = json.loads(message)["payload"]
        self.sent.append(payload)
        if payload["params"]["name"] == STATUS_TOOL:
            value = {"audio_speaker": {"volume": self.volume}, "network": "private-not-for-api"}
        else:
            self.volume = payload["params"]["arguments"]["volume"]
            value = True
        # 走上游真实结果路由，而非测试直接把 Future 标记为完成。
        await handler_module.handle_mcp_message(self, self.mcp_client, {
            "id": payload["id"], "result": {
                "content": [{"type": "text", "text": json.dumps(value)}], "isError": False}})


async def run_cli(port, token_path, *args):
    code = (
        "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
        "import control; control.PORT=int(sys.argv[2]); control.TOKEN_FILE=Path(sys.argv[3]); "
        "raise SystemExit(control.main(sys.argv[4:]))"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, str(SCRIPTS), str(port), str(token_path), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    assert not stderr, stderr.decode(errors="replace")
    return process.returncode, json.loads(stdout)


async def run():
    device = Device()
    announcements = []

    async def queue_announcement(conn, text):
        announcements.append((conn, text))
    # 输入来自设备握手工具列表，检验上游原名 -> 净化名转换不影响定向调用。
    await handler_module.handle_mcp_message(device, device.mcp_client, {
        "id": 2, "result": {"tools": [
            {"name": STATUS_TOOL, "inputSchema": {"type": "object", "properties": {}}},
            {"name": VOLUME_TOOL, "inputSchema": {"type": "object", "properties": {
                "volume": {"type": "integer", "minimum": 0, "maximum": 100}}, "required": ["volume"]}},
        ]}})
    bridge = DeviceControl(
        "aa:bb:cc:dd:ee:ff", announcement_sender=queue_announcement
    )
    device.loop = asyncio.get_running_loop()
    device.client_is_speaking = False
    device.client_have_voice = False
    device.calling = False
    device.tts = types.SimpleNamespace(
        tts_text_queue=asyncio.Queue(), tts_audio_queue=asyncio.Queue()
    )
    bridge.attach(device, "aa:bb:cc:dd:ee:ff")
    with tempfile.TemporaryDirectory(prefix="control-probe-") as directory:
        token_path = Path(directory) / "control.token"
        token = ensure_token(token_path)
        assert ensure_token(token_path) == token
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        runner = web.AppRunner(create_app(bridge, token, port), access_log=None)
        try:
            await runner.setup()
            await web.SockSite(runner, sock).start()
            base = f"http://127.0.0.1:{port}"
            auth = {"Authorization": f"Bearer {token}"}
            async with ClientSession(trust_env=False) as session:
                cases = [
                    ({}, 401), ({"Authorization": "Bearer wrong"}, 401),
                    ({**auth, "Origin": "https://evil.invalid"}, 403),
                    ({**auth, "Origin": base}, 403),
                    ({**auth, "Sec-Fetch-Site": "same-origin"}, 403),
                    ({**auth, "Host": "evil.invalid"}, 403),
                ]
                for headers, expected in cases:
                    async with session.post(base + "/api/device/volume", headers=headers,
                                            json={"volume": 30}) as response:
                        assert response.status == expected
                assert not device.sent
                for payload, expected in [({"volume": True}, 400), ({"volume": 99}, 400),
                                          ({"volume": 30, "tool": "arbitrary"}, 400)]:
                    async with session.post(base + "/api/device/volume", headers=auth,
                                            json=payload) as response:
                        assert response.status == expected
                async with session.post(base + "/api/device/volume", headers=auth,
                                        data="volume=30") as response:
                    assert response.status == 415
                async with session.post(base + "/api/device/volume", headers={
                    **auth, "Content-Type": "application/json"}, data='{"volume":30,"x":"' + 'x'*1100 + '"}') as response:
                    assert response.status == 413
                async with session.post(base + "/api/device/volume", headers={
                    **auth, "Content-Type": "application/json"}, data="broken") as response:
                    assert response.status == 400
                async with session.delete(base + "/api/device/volume", headers=auth) as response:
                    assert response.status == 405
                assert not device.sent
            code, state = await run_cli(port, token_path, "status")
            assert code == 0 and state["set_volume_supported"]
            assert not device.sent
            code, result = await run_cli(port, token_path, "set-volume", "30")
            assert code == 0 and result["verified"] and result["readback_volume"] == 30
            assert len(device.sent) == 3 and device.volume == 30
            assert "private-not-for-api" not in json.dumps(result)
            assert not device.mcp_client.call_results
            code, result = await run_cli(port, token_path, "read-volume")
            assert code == 0 and result == {"volume": 30}
            code, result = await run_cli(
                port, token_path, "announce", "这是一条主动播报通道测试。",
                "--ttl-seconds", "30"
            )
            assert code == 0 and result["state"] == "queued"
            assert result["playback_acknowledgement"] == "unavailable"
            assert announcements == [(device, "这是一条主动播报通道测试。")]
        finally:
            await runner.cleanup()
            sock.close()
    print("PASS: independent CLI -> loopback HTTP -> upstream MCP dispatch -> simulated device acknowledgement/readback")


if __name__ == "__main__":
    asyncio.run(run())
