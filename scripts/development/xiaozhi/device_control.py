"""单圆屏控制通道：不调用 LLM、不写记忆、不提供任意工具执行入口。

运行在小智的事件循环中；连接由已完成上游认证的 handle_connection 注册。
设备身份仍受上游自报 MAC 的限制，不把它当作生产级认证。
"""

import asyncio
import json
import time
from uuid import uuid4


STATUS_TOOL = "self.get_device_status"
VOLUME_TOOL = "self.audio_speaker.set_volume"
BRIGHTNESS_TOOL = "self.screen.set_brightness"
THEME_TOOL = "self.screen.set_theme"
MIN_VOLUME, MAX_VOLUME = 5, 60  # 技术验证阶段限制，非硬件音量范围。
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 5, 100
MAX_ANNOUNCEMENT_CHARS = 80
MAX_ANNOUNCEMENT_TTL_SECONDS = 300


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
    definitions = {
        VOLUME_TOOL: ("volume", "integer"),
        BRIGHTNESS_TOOL: ("brightness", "integer"),
        THEME_TOOL: ("theme", "string"),
    }
    field, expected_type = definitions.get(original_name, (None, None))
    value = properties.get(field, {}) if isinstance(properties, dict) and field else {}
    if value.get("type") != expected_type or set(required) - {field}:
        raise ControlError("tool_schema_unsupported")
    if expected_type == "integer":
        for bound, default in (("minimum", 0), ("maximum", 100)):
            if type(value.get(bound, default)) is not int:
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
    def __init__(self, allowed_device_id, timeout=5, announcement_sender=None):
        self.allowed_device_id = allowed_device_id.lower()
        self.timeout = timeout
        self.announcement_sender = announcement_sender or enqueue_announcement
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
                  "read_status_supported": False, "set_brightness_supported": False,
                  "set_theme_supported": False,
                  "aec_advertised": False,
                  "announcement_supported": False, "announcement_ready": False,
                  "user_session_active": False,
                  "allowed_volume": {"minimum": MIN_VOLUME, "maximum": MAX_VOLUME}}
        try:
            conn = self._connection()
            result["ready"] = True
            # AEC 是自由说话打断的必要基础之一，但仅凭握手字段不能证明整条打断链路可用。
            result["aec_advertised"] = getattr(conn, "features", {}).get("aec") is True
            for name, field in ((STATUS_TOOL, "read_status_supported"),
                                (STATUS_TOOL, "read_volume_supported"),
                                (VOLUME_TOOL, "set_volume_supported"),
                                (BRIGHTNESS_TOOL, "set_brightness_supported"),
                                (THEME_TOOL, "set_theme_supported")):
                try:
                    tool_schema(conn.mcp_client, name)
                    result[field] = True
                except ControlError:
                    pass
            tts = getattr(conn, "tts", None)
            if (tts is not None and getattr(conn, "loop", None) is not None
                    and hasattr(tts, "tts_text_queue")
                    and hasattr(tts, "tts_audio_queue")):
                result["announcement_supported"] = True
                active = (getattr(conn, "client_is_speaking", False)
                          or getattr(conn, "client_have_voice", False)
                          or getattr(conn, "calling", False))
                result["user_session_active"] = active
                busy = (active
                        or not tts.tts_text_queue.empty()
                        or not tts.tts_audio_queue.empty())
                result["announcement_ready"] = not busy
                if busy:
                    result["announcement_reason"] = "device_busy"
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
        if name not in (STATUS_TOOL, VOLUME_TOOL, BRIGHTNESS_TOOL, THEME_TOOL):
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
        status = await self._read_status(conn)
        speaker = status.get("audio_speaker", {}) if isinstance(status, dict) else {}
        volume = speaker.get("volume") if isinstance(speaker, dict) else None
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ControlError("volume_readback_unavailable", 502)
        # 完整状态可能包含网络/电量等信息，控制 API 只保留所需音量。
        return volume

    async def _read_status(self, conn):
        status = await self._call(conn, STATUS_TOOL, {})
        if not isinstance(status, dict):
            raise ControlError("status_readback_unavailable", 502)
        return status

    @staticmethod
    def _project_status(status):
        """只向控制台暴露产品需要的状态，不返回 SSID 等网络标识。"""
        result = {}
        speaker = status.get("audio_speaker")
        if isinstance(speaker, dict) and type(speaker.get("volume")) is int and 0 <= speaker["volume"] <= 100:
            result["volume"] = speaker["volume"]
        screen = status.get("screen")
        if isinstance(screen, dict):
            if type(screen.get("brightness")) is int and 0 <= screen["brightness"] <= 100:
                result["brightness"] = screen["brightness"]
            if screen.get("theme") in {"light", "dark"}:
                result["theme"] = screen["theme"]
        battery = status.get("battery")
        if isinstance(battery, dict) and type(battery.get("level")) is int and 0 <= battery["level"] <= 100 and type(battery.get("charging")) is bool:
            result["battery"] = {"level": battery["level"], "charging": battery["charging"]}
        network = status.get("network")
        if isinstance(network, dict) and network.get("signal") in {"strong", "medium", "weak"}:
            result["network"] = {"signal": network["signal"]}
        chip = status.get("chip")
        temperature = chip.get("temperature") if isinstance(chip, dict) else None
        if type(temperature) in {int, float} and -40 <= temperature <= 125:
            result["chip"] = {"temperature": round(float(temperature), 1)}
        if not result:
            raise ControlError("status_readback_unavailable", 502)
        return result

    async def read_status(self):
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            return self._project_status(await self._read_status(conn))

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

    async def _set_screen_value(self, *, tool, field, value):
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            schema = tool_schema(conn.mcp_client, tool)
            prop = schema["properties"][field]
            if type(value) is int and not prop.get("minimum", 0) <= value <= prop.get("maximum", 100):
                raise ControlError("value_outside_device_schema", 400)
            before_status = self._project_status(await self._read_status(conn))
            acknowledged = await self._call(conn, tool, {field: value})
            if acknowledged is not True:
                raise ControlError("set_not_acknowledged_outcome_unknown", 502)
            result = {"requested_value": value, "previous_value": before_status.get(field),
                      "acknowledged": True, "readback_value": None, "verified": False}
            try:
                after = self._project_status(await self._read_status(conn))
                result["readback_value"] = after.get(field)
                result["verified"] = result["readback_value"] == value
                if not result["verified"]:
                    result["reason"] = "readback_mismatch"
            except ControlError as exc:
                result["reason"] = exc.code
            result["operation_id"] = uuid4().hex
            return result

    async def set_brightness(self, brightness):
        if type(brightness) is not int or not MIN_BRIGHTNESS <= brightness <= MAX_BRIGHTNESS:
            raise ControlError("brightness_out_of_range", 400)
        return await self._set_screen_value(tool=BRIGHTNESS_TOOL, field="brightness", value=brightness)

    async def set_theme(self, theme):
        if theme not in {"light", "dark"}:
            raise ControlError("theme_invalid", 400)
        return await self._set_screen_value(tool=THEME_TOOL, field="theme", value=theme)

    async def announce(self, text, expires_at_ms):
        """把一条短测试文本放入当前连接的既有 TTS 队列。

        这里的成功只表示服务端已接受并排队；当前协议没有设备播放完成回执，
        因此绝不返回 acknowledged/played 之类会夸大结果的状态。
        """
        if (not isinstance(text, str) or text != text.strip()
                or not text or len(text) > MAX_ANNOUNCEMENT_CHARS
                or any(ord(char) < 32 for char in text)):
            raise ControlError("invalid_announcement", 400)
        if type(expires_at_ms) is not int:
            raise ControlError("invalid_expiry", 400)
        remaining_ms = expires_at_ms - int(time.time() * 1000)
        if remaining_ms <= 0:
            raise ControlError("announcement_expired", 409)
        if remaining_ms > MAX_ANNOUNCEMENT_TTL_SECONDS * 1000:
            raise ControlError("invalid_expiry", 400)
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            tts = getattr(conn, "tts", None)
            if (tts is None or getattr(conn, "loop", None) is None
                    or not hasattr(tts, "tts_text_queue")
                    or not hasattr(tts, "tts_audio_queue")):
                raise ControlError("tts_not_ready")
            # 不打断用户讲话、模型回答或尚未发完的音频；第一版也不排队等待。
            if (getattr(conn, "client_is_speaking", False)
                    or getattr(conn, "client_have_voice", False)
                    or getattr(conn, "calling", False)
                    or not tts.tts_text_queue.empty()
                    or not tts.tts_audio_queue.empty()):
                raise ControlError("device_busy")
            operation_id = uuid4().hex
            try:
                await self.announcement_sender(conn, text)
            except ControlError:
                raise
            except Exception:
                raise ControlError("announcement_enqueue_failed", 502) from None
            return {
                "operation_id": operation_id,
                "state": "queued",
                "playback_acknowledgement": "unavailable",
                "expires_at_ms": expires_at_ms,
            }


async def enqueue_announcement(conn, text):
    """复用固定小智快照的 TTS 生命周期，不写对话历史、不调用模型。"""
    from core.handle.sendAudioHandle import send_tts_message
    from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType

    sentence_id = uuid4().hex
    conn.client_abort = False
    conn.sentence_id = sentence_id
    await send_tts_message(conn, "start")
    conn.client_is_speaking = True
    conn.tts.store_tts_text(sentence_id, text)
    conn.tts.tts_text_queue.put(TTSMessageDTO(
        sentence_id=sentence_id,
        sentence_type=SentenceType.FIRST,
        content_type=ContentType.ACTION,
    ))
    conn.tts.tts_one_sentence(
        conn, ContentType.TEXT, content_detail=text, sentence_id=sentence_id
    )
    conn.tts.tts_text_queue.put(TTSMessageDTO(
        sentence_id=sentence_id,
        sentence_type=SentenceType.LAST,
        content_type=ContentType.ACTION,
    ))


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
