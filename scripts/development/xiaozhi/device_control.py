"""单圆屏控制通道：不调用 LLM、不写记忆、不提供任意工具执行入口。

运行在小智的事件循环中；连接由已完成上游认证的 handle_connection 注册。
设备身份仍受上游自报 MAC 的限制，不把它当作生产级认证。
"""

import asyncio
import json
from uuid import uuid4


STATUS_TOOL = "self.get_device_status"
VOLUME_TOOL = "self.audio_speaker.set_volume"
MIN_VOLUME, MAX_VOLUME = 5, 60  # 技术验证阶段限制，非硬件音量范围。


class ControlError(Exception):
    """只用固定错误码跨进程返回，不泄露上游异常、对话或设备状态全文。"""

    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def tool_schema(client, original_name):
    """使用当前连接上报的原始工具名，不依据旧固件文件猜测支持情况。"""
    matches = [tool for tool in client.tools.values()
               if tool.get("name") == original_name]
    if len(matches) != 1:
        raise ControlError("tool_unavailable")
    schema = matches[0].get("inputSchema", {})
    if schema.get("type") != "object":
        raise ControlError("tool_schema_unsupported")
    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ControlError("tool_schema_unsupported")
    if original_name == STATUS_TOOL:
        if required:
            raise ControlError("tool_schema_unsupported")
        return schema
    properties = schema.get("properties", {})
    volume = properties.get("volume", {}) if isinstance(properties, dict) else {}
    if volume.get("type") != "integer" or set(required) - {"volume"}:
        raise ControlError("tool_schema_unsupported")
    for field, default in (("minimum", 0), ("maximum", 100)):
        if type(volume.get(field, default)) is not int:
            raise ControlError("tool_schema_unsupported")
    return schema


def decode_result(result):
    """当前 ESP32 MCP 返回一个 JSON 文本块；未知格式不猜测成功。"""
    if not isinstance(result, dict) or result.get("isError", False) is not False:
        raise ControlError("device_rejected", 502)
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ControlError("unexpected_device_result", 502)
    block = content[0]
    if not isinstance(block, dict) or block.get("type") != "text":
        raise ControlError("unexpected_device_result", 502)
    text = block.get("text")
    if not isinstance(text, str) or len(text) > 8192:
        raise ControlError("unexpected_device_result", 502)
    try:
        return json.loads(text)
    except ValueError:
        raise ControlError("unexpected_device_result", 502) from None


class DeviceControl:
    def __init__(self, allowed_device_id, timeout=5):
        self.allowed_device_id = allowed_device_id.lower()
        self.timeout = timeout
        self.connections = {}
        self.operation_lock = asyncio.Lock()

    def attach(self, connection, device_id):
        if isinstance(device_id, str) and device_id.lower() == self.allowed_device_id:
            self.connections[id(connection)] = connection

    def detach(self, connection):
        self.connections.pop(id(connection), None)

    def _connection(self):
        if not self.connections:
            raise ControlError("device_offline")
        if len(self.connections) != 1:
            raise ControlError("ambiguous_device_connections")
        conn = next(iter(self.connections.values()))
        ws = getattr(conn, "websocket", None)
        if getattr(getattr(ws, "state", None), "name", None) != "OPEN":
            raise ControlError("device_offline")
        bound = getattr(conn, "bind_completed_event", None)
        if bound is None or not bound.is_set() or getattr(conn, "need_bind", True):
            raise ControlError("device_not_ready")
        client = getattr(conn, "mcp_client", None)
        if not getattr(conn, "features", {}).get("mcp") or not client or not client.ready:
            raise ControlError("tools_not_ready")
        return conn

    def status(self):
        """只读缓存的握手状态；此接口不向圆屏发命令，也不返回工具描述全文。"""
        result = {"connection_count": len(self.connections), "ready": False,
                  "read_volume_supported": False, "set_volume_supported": False,
                  "allowed_volume": {"minimum": MIN_VOLUME, "maximum": MAX_VOLUME}}
        try:
            conn = self._connection()
            result["ready"] = True
            for name, field in ((STATUS_TOOL, "read_volume_supported"),
                                (VOLUME_TOOL, "set_volume_supported")):
                try:
                    tool_schema(conn.mcp_client, name)
                    result[field] = True
                except ControlError:
                    pass
        except ControlError as exc:
            result["reason"] = exc.code
        return result

    async def _call(self, conn, name, arguments):
        """复用小智 MCP 的回执路由，直接发送以避免上游辅助函数吞掉发送异常。

        握手固定占用 ID 1/2；工具调用跳过它们，并使用上游共享计数器。
        无论成功、断线、异常或取消，都清理本次 Future；不自动重试。
        """
        if self._connection() is not conn:
            raise ControlError("device_connection_changed")
        if name not in (STATUS_TOOL, VOLUME_TOOL):
            raise ControlError("tool_not_allowed", 403)
        client = conn.mcp_client
        tool_schema(client, name)
        call_id = await client.get_next_id()
        while call_id < 3:
            call_id = await client.get_next_id()
        future = asyncio.get_running_loop().create_future()
        await client.register_call_result_future(call_id, future)
        message = {"type": "mcp", "payload": {"jsonrpc": "2.0", "id": call_id,
                   "method": "tools/call", "params": {"name": name, "arguments": arguments}}}
        try:
            async def exchange():
                await conn.websocket.send(json.dumps(message))
                return await future
            raw = await asyncio.wait_for(exchange(), timeout=self.timeout)
            return decode_result(raw)
        except asyncio.TimeoutError:
            raise ControlError("device_timeout_outcome_unknown", 504) from None
        except ControlError:
            raise
        except Exception:
            raise ControlError("device_call_failed_outcome_unknown", 502) from None
        finally:
            await client.cleanup_call_result(call_id)
            if not future.done():
                future.cancel()

    async def _read_volume(self, conn):
        status = await self._call(conn, STATUS_TOOL, {})
        speaker = status.get("audio_speaker", {}) if isinstance(status, dict) else {}
        volume = speaker.get("volume") if isinstance(speaker, dict) else None
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ControlError("volume_readback_unavailable", 502)
        # 完整状态可能包含网络/电量等信息，控制 API 只保留所需音量。
        return volume

    async def read_volume(self):
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            return {"volume": await self._read_volume(self._connection())}

    async def set_volume(self, volume):
        if type(volume) is not int or not MIN_VOLUME <= volume <= MAX_VOLUME:
            raise ControlError("volume_out_of_range", 400)
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            schema = tool_schema(conn.mcp_client, VOLUME_TOOL)
            prop = schema["properties"]["volume"]
            if not prop.get("minimum", 0) <= volume <= prop.get("maximum", 100):
                raise ControlError("volume_outside_device_schema", 400)
            before = await self._read_volume(conn)
            acknowledged = await self._call(conn, VOLUME_TOOL, {"volume": volume})
            if acknowledged is not True:
                raise ControlError("set_not_acknowledged_outcome_unknown", 502)
            result = {"requested_volume": volume, "previous_volume": before,
                      "acknowledged": True, "readback_volume": None, "verified": False}
            try:
                result["readback_volume"] = await self._read_volume(conn)
                result["verified"] = result["readback_volume"] == volume
                if not result["verified"]:
                    result["reason"] = "readback_mismatch"
            except ControlError as exc:
                # 写操作已获回执，不能把后续读取失败说成“没修改”，也不能自动重试。
                result["reason"] = exc.code
            result["operation_id"] = uuid4().hex
            return result


def install_connection_tracking(connection_class, control):
    original = connection_class.handle_connection

    async def handle(connection, ws):
        # 此方法在固定上游快照中仅于认证完成后调用；不绕过其认证流程。
        control.attach(connection, ws.request.headers.get("device-id"))
        try:
            return await original(connection, ws)
        finally:
            control.detach(connection)

    connection_class.handle_connection = handle
