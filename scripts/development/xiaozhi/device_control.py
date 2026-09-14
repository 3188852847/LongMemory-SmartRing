"""单圆屏控制通道：不调用 LLM、不写记忆、不提供任意工具执行入口。

运行在小智的事件循环中；连接由已完成上游认证的 handle_connection 注册。
设备身份仍受上游自报 MAC 的限制，不把它当作生产级认证。
"""

import asyncio
import json
import re
import time
import ipaddress
from urllib.parse import urlsplit
from uuid import uuid4


STATUS_TOOL = "self.get_device_status"
VOLUME_TOOL = "self.audio_speaker.set_volume"
BRIGHTNESS_TOOL = "self.screen.set_brightness"
THEME_TOOL = "self.screen.set_theme"
GET_ROUND_SKIN_TOOL = "self.screen.get_round_skin"
SET_ROUND_SKIN_TOOL = "self.screen.set_round_skin"
STAGE_ROUND_WALLPAPER_TOOL = "self.screen.stage_round_wallpaper"
GET_ROUND_WALLPAPER_TOOL = "self.screen.get_round_wallpaper"
ACTIVATE_ROUND_WALLPAPER_TOOL = "self.screen.activate_round_wallpaper"
ROLLBACK_ROUND_WALLPAPER_TOOL = "self.screen.rollback_round_wallpaper"
DEACTIVATE_ROUND_WALLPAPER_TOOL = "self.screen.deactivate_round_wallpaper"
REBOOT_TOOL = "self.reboot"
MIN_VOLUME, MAX_VOLUME = 5, 60  # 技术验证阶段限制，非硬件音量范围。
MIN_BRIGHTNESS, MAX_BRIGHTNESS = 5, 100
MAX_ANNOUNCEMENT_CHARS = 80
MAX_ANNOUNCEMENT_TTL_SECONDS = 300
MAX_WALLPAPER_BYTES = 4 * 1024 * 1024
WALLPAPER_RESTART_CONFIRM_SECONDS = 90
ROUND_SKIN_FIELDS = (
    "skin_api", "skin_id", "manifest_sha256", "background", "foreground", "muted",
    "accent", "listening", "thinking", "happy", "concerned", "error",
    "eye_width", "eye_height", "mouth_width",
)
ROUND_SKIN_COLOR_FIELDS = (
    "background", "foreground", "muted", "accent", "listening", "thinking",
    "happy", "concerned", "error",
)


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


def validate_round_skin(value):
    """验证固件回读与即将下发的 skin_api=1 子集，拒绝设备返回的开放字段。"""
    if not isinstance(value, dict) or set(value) != set(ROUND_SKIN_FIELDS):
        raise ControlError("round_skin_readback_invalid", 502)
    if value.get("skin_api") != 1:
        raise ControlError("round_skin_readback_invalid", 502)
    if (not isinstance(value.get("skin_id"), str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", value["skin_id"]) is None
            or not isinstance(value.get("manifest_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["manifest_sha256"]) is None):
        raise ControlError("round_skin_readback_invalid", 502)
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= 0xFFFFFF
           for key in ROUND_SKIN_COLOR_FIELDS):
        raise ControlError("round_skin_readback_invalid", 502)
    for key, minimum, maximum in (
        ("eye_width", 12, 36), ("eye_height", 18, 48), ("mouth_width", 20, 64),
    ):
        if type(value.get(key)) is not int or not minimum <= value[key] <= maximum:
            raise ControlError("round_skin_readback_invalid", 502)
    return value


def validate_wallpaper_result(value, expected_state):
    fields = {"wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes", "state"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ControlError("round_wallpaper_readback_invalid", 502)
    if (value.get("wallpaper_api") != 1 or value.get("slot") not in {"a", "b"}
            or value.get("state") != expected_state
            or not isinstance(value.get("wallpaper_id"), str)
            or re.fullmatch(r"wallpaper-[0-9a-f]{20}", value["wallpaper_id"]) is None
            or not isinstance(value.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            or type(value.get("size_bytes")) is not int
            or not 0 < value["size_bytes"] <= MAX_WALLPAPER_BYTES):
        raise ControlError("round_wallpaper_readback_invalid", 502)
    return value


def validate_wallpaper_status(value):
    fields = {"wallpaper_api", "active_valid", "active_slot", "active_wallpaper_id",
              "active_sha256", "active_size_bytes", "rollback_available"}
    if not isinstance(value, dict) or set(value) != fields or value.get("wallpaper_api") != 1:
        raise ControlError("round_wallpaper_readback_invalid", 502)
    if type(value.get("active_valid")) is not bool or type(value.get("rollback_available")) is not bool:
        raise ControlError("round_wallpaper_readback_invalid", 502)
    if value["active_valid"]:
        valid = (value.get("active_slot") in {"a", "b"}
                 and re.fullmatch(r"wallpaper-[0-9a-f]{20}", str(value.get("active_wallpaper_id", "")))
                 and re.fullmatch(r"[0-9a-f]{64}", str(value.get("active_sha256", "")))
                 and type(value.get("active_size_bytes")) is int
                 and 0 < value["active_size_bytes"] <= MAX_WALLPAPER_BYTES)
    else:
        valid = (
            value.get("active_slot") == ""
            and value.get("active_wallpaper_id") == ""
            and value.get("active_sha256") == ""
            and value.get("active_size_bytes") == 0
        )
    if not valid:
        raise ControlError("round_wallpaper_readback_invalid", 502)
    return value


def validate_wallpaper_url(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ControlError("round_wallpaper_stage_invalid", 400)
    parsed = urlsplit(value)
    try:
        address = ipaddress.IPv4Address(parsed.hostname or "")
    except ipaddress.AddressValueError:
        raise ControlError("round_wallpaper_stage_invalid", 400) from None
    try:
        port = parsed.port
    except ValueError:
        raise ControlError("round_wallpaper_stage_invalid", 400) from None
    private = any(address in ipaddress.ip_network(network) for network in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    ))
    if (parsed.scheme != "http" or port != 8768 or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or re.fullmatch(r"/wallpaper/[0-9a-f]{64}", parsed.path) is None
            or not private):
        raise ControlError("round_wallpaper_stage_invalid", 400)
    return value


async def abort_current_response(connection):
    """复用小智已有的中止语义：停止模型/TTS工作、清空队列并向设备发 tts stop。"""
    from core.handle.abortHandle import handleAbortMessage
    await handleAbortMessage(connection)


def natural_interruption_diagnostics(connection=None):
    """给出自然说话打断的保守能力判定，不把单个 AEC 声明当成完整闭环。

    当前固定小智快照只在 MQTT 网关路径解析带时间戳的音频头并维护
    播放参考缓存。直连 WebSocket 即使客户端声明 AEC，也缺少这段配对
    语义，因此不能声称服务端回声消除已经可用。
    """
    if connection is None:
        return {
            "version": 1,
            "state": "unavailable",
            "device_aec_advertised": False,
            "server_aec_active": False,
            "timestamped_audio_supported": False,
            "listen_mode": "unknown",
            "reason": "device_offline",
        }

    features = getattr(connection, "features", {})
    device_aec = isinstance(features, dict) and features.get("aec") is True
    server_aec = getattr(connection, "client_aec", False) is True
    headers = getattr(connection, "headers", {})
    raw_protocol = next((value for key, value in headers.items()
                         if isinstance(key, str) and key.lower() == "protocol-version"), "1") \
        if isinstance(headers, dict) else "1"
    try:
        protocol_v2 = int(raw_protocol) == 2
    except (TypeError, ValueError):
        protocol_v2 = False
    # MQTT 原生支持时间戳；直连只有在项目包装器已安装且客户端明确选择 v2 时支持。
    direct_v2_installed = (
        getattr(connection, "_longmemory_direct_ws_v2_installed", False) is True
        or getattr(type(connection), "_longmemory_direct_ws_v2_installed", False) is True
    )
    timestamped_audio = (getattr(connection, "conn_from_mqtt_gateway", False) is True
                         or (protocol_v2 and direct_v2_installed))
    raw_mode = getattr(connection, "client_listen_mode", "unknown")
    listen_mode = raw_mode if raw_mode in {"auto", "manual", "realtime"} else "unknown"

    if not device_aec:
        reason = "device_aec_not_advertised"
    elif not timestamped_audio:
        reason = "timestamp_transport_unavailable"
    elif not server_aec:
        reason = "server_aec_inactive"
    elif listen_mode != "realtime":
        reason = "realtime_listening_inactive"
    else:
        reason = "ready_for_controlled_trial"

    return {
        "version": 1,
        "state": "trial_ready" if reason == "ready_for_controlled_trial" else "blocked",
        "device_aec_advertised": device_aec,
        "server_aec_active": server_aec,
        "timestamped_audio_supported": timestamped_audio,
        "listen_mode": listen_mode,
        "reason": reason,
    }


class DeviceControl:
    def __init__(self, allowed_device_id, timeout=5, announcement_sender=None,
                 response_aborter=None):
        self.allowed_device_id = allowed_device_id.lower()
        self.timeout = timeout
        self.announcement_sender = announcement_sender or enqueue_announcement
        self.response_aborter = response_aborter or abort_current_response
        self.connections = {}
        self.operation_lock = asyncio.Lock()
        # 最近一轮只包含阶段时间和后端名，不含用户问题、回答正文或音频。
        # 设备回到待机并断开控制连接后仍保留，下一轮样本会覆盖它。
        self.last_voice_latency = None

    def attach(self, connection, device_id):
        if isinstance(device_id, str) and device_id.lower() == self.allowed_device_id:
            self.connections[id(connection)] = connection

    def detach(self, connection):
        tracker = getattr(connection, "_longmemory_voice_latency", None)
        if tracker is not None:
            latency = tracker.snapshot()
            if latency is not None:
                self.last_voice_latency = latency
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
                  "stop_speech_supported": False,
                  "user_session_active": False,
                  "natural_interruption": natural_interruption_diagnostics(),
                  "allowed_volume": {"minimum": MIN_VOLUME, "maximum": MAX_VOLUME}}
        try:
            conn = self._connection()
            result["ready"] = True
            # AEC 是自由说话打断的必要基础之一，但仅凭握手字段不能证明整条打断链路可用。
            result["aec_advertised"] = getattr(conn, "features", {}).get("aec") is True
            result["natural_interruption"] = natural_interruption_diagnostics(conn)
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
                # 这是小智服务端的中止能力，不依赖设备 MCP 工具。
                # 它能确认服务端已清队列，但设备协议没有播放停止回执。
                result["stop_speech_supported"] = True
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
            tracker = getattr(conn, "_longmemory_voice_latency", None)
            if tracker is not None:
                latency = tracker.snapshot()
                if latency is not None:
                    self.last_voice_latency = latency
        except ControlError as exc:
            result["reason"] = exc.code
        if self.last_voice_latency is not None:
            result["voice_latency"] = self.last_voice_latency
        return result

    async def _call(self, conn, name, arguments, *, timeout=None):
        """复用小智 MCP 的回执路由，直接发送以避免上游辅助函数吞掉发送异常。

        握手固定占用 ID 1/2；工具调用跳过它们，并使用上游共享计数器。
        无论成功、断线、异常或取消，都清理本次 Future；不自动重试。
        """
        if self._connection() is not conn:
            raise ControlError("device_connection_changed")
        if name not in (STATUS_TOOL, VOLUME_TOOL, BRIGHTNESS_TOOL, THEME_TOOL,
                        GET_ROUND_SKIN_TOOL, SET_ROUND_SKIN_TOOL,
                        GET_ROUND_WALLPAPER_TOOL, STAGE_ROUND_WALLPAPER_TOOL, ACTIVATE_ROUND_WALLPAPER_TOOL,
                        ROLLBACK_ROUND_WALLPAPER_TOOL, DEACTIVATE_ROUND_WALLPAPER_TOOL,
                        REBOOT_TOOL):
            raise ControlError("tool_not_allowed", 403)
        client = conn.mcp_client
        # 皮肤工具在固件中标为 user-only，避免语言模型擅自修改外观；因此不会
        # 出现在普通 tools/list 中。只有本机窄控制通道能按固定契约直接调用。
        if name not in (GET_ROUND_SKIN_TOOL, SET_ROUND_SKIN_TOOL,
                        GET_ROUND_WALLPAPER_TOOL, STAGE_ROUND_WALLPAPER_TOOL, ACTIVATE_ROUND_WALLPAPER_TOOL,
                        ROLLBACK_ROUND_WALLPAPER_TOOL, DEACTIVATE_ROUND_WALLPAPER_TOOL,
                        REBOOT_TOOL):
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
            raw = await asyncio.wait_for(
                exchange(), timeout=self.timeout if timeout is None else timeout,
            )
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

    async def stop_speech(self):
        """确定性地中止当前服务端回答，不将“指令已发”冒充为硬件回执。"""
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            if getattr(conn, "tts", None) is None or getattr(conn, "loop", None) is None:
                raise ControlError("stop_speech_unavailable")
            active = (
                getattr(conn, "client_is_speaking", False)
                or not conn.tts.tts_text_queue.empty()
                or not conn.tts.tts_audio_queue.empty()
            )
            operation_id = uuid4().hex
            if not active:
                return {
                    "operation_id": operation_id,
                    "state": "already_idle",
                    "server_interrupted": False,
                    "device_acknowledgement": "not_requested",
                }
            await self.response_aborter(conn)
            return {
                "operation_id": operation_id,
                "state": "stop_sent",
                "server_interrupted": True,
                "device_acknowledgement": "unavailable",
            }

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

    async def read_round_skin(self):
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            return validate_round_skin(
                await self._call(self._connection(), GET_ROUND_SKIN_TOOL, {})
            )

    async def set_round_skin(self, skin):
        try:
            requested = validate_round_skin(skin)
        except ControlError:
            raise ControlError("round_skin_invalid", 400) from None
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            conn = self._connection()
            acknowledged = await self._call(conn, SET_ROUND_SKIN_TOOL, requested)
            if acknowledged is not True:
                raise ControlError("set_not_acknowledged_outcome_unknown", 502)
            result = {
                "requested_skin_id": requested["skin_id"],
                "requested_manifest_sha256": requested["manifest_sha256"],
                "acknowledged": True,
                "verified": False,
            }
            try:
                readback = validate_round_skin(
                    await self._call(conn, GET_ROUND_SKIN_TOOL, {})
                )
                result["device_skin"] = readback
                result["verified"] = readback == requested
                if not result["verified"]:
                    result["reason"] = "round_skin_readback_mismatch"
            except ControlError as exc:
                result["reason"] = exc.code
            result["operation_id"] = uuid4().hex
            return result

    async def stage_round_wallpaper(self, *, item_id, sha256, size_bytes, url):
        if (not isinstance(item_id, str)
                or re.fullmatch(r"wallpaper-[0-9a-f]{20}", item_id) is None
                or not isinstance(sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
                or type(size_bytes) is not int
                or not 0 < size_bytes <= MAX_WALLPAPER_BYTES):
            raise ControlError("round_wallpaper_stage_invalid", 400)
        validate_wallpaper_url(url)
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            result = validate_wallpaper_result(await self._call(
                self._connection(), STAGE_ROUND_WALLPAPER_TOOL,
                {"wallpaper_api": 1, "wallpaper_id": item_id, "sha256": sha256,
                 "size_bytes": size_bytes, "url": url},
                timeout=120,
            ), "staged_verified")
            if (result["wallpaper_id"] != item_id or result["sha256"] != sha256
                    or result["size_bytes"] != size_bytes):
                raise ControlError("round_wallpaper_readback_mismatch", 502)
            return {**result, "operation_id": uuid4().hex}

    async def read_round_wallpaper(self):
        return validate_wallpaper_status(await self._call(
            self._connection(), GET_ROUND_WALLPAPER_TOOL, {},
        ))

    async def activate_round_wallpaper(self, staged):
        staged = validate_wallpaper_result(staged, "staged_verified")
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            arguments = {
                "wallpaper_api": 1,
                "slot": staged["slot"],
                "wallpaper_id": staged["wallpaper_id"],
                "sha256": staged["sha256"],
                "size_bytes": staged["size_bytes"],
            }
            selected = validate_wallpaper_result(await self._call(
                self._connection(), ACTIVATE_ROUND_WALLPAPER_TOOL, arguments,
            ), "activation_pending_restart")
            if any(selected[key] != arguments[key] for key in arguments):
                raise ControlError("round_wallpaper_readback_mismatch", 502)
            reboot_connection = self._connection()
            try:
                if await self._call(reboot_connection, REBOOT_TOOL, {}) is not True:
                    raise ControlError("round_wallpaper_restart_not_acknowledged", 502)
            except ControlError as exc:
                # ESP32 可能先执行重启、再来不及把 `true` 回执刷到 WebSocket。
                # 这时不能重发 reboot，更不能把已经成功的安装显示成失败；只等待
                # 新连接并读取活动槽，且必须与刚才选择的完整记录严格一致。
                if exc.code not in {
                    "device_timeout_outcome_unknown", "device_call_failed_outcome_unknown",
                    "device_connection_changed",
                }:
                    raise
                await self._confirm_round_wallpaper_after_restart(selected, reboot_connection)
            return {**selected, "state": "activated_restarting", "operation_id": uuid4().hex}

    async def rollback_round_wallpaper(self):
        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            selected = validate_wallpaper_result(await self._call(
                self._connection(), ROLLBACK_ROUND_WALLPAPER_TOOL,
                {"wallpaper_api": 1},
            ), "rollback_pending_restart")
            reboot_connection = self._connection()
            try:
                if await self._call(reboot_connection, REBOOT_TOOL, {}) is not True:
                    raise ControlError("round_wallpaper_restart_not_acknowledged", 502)
            except ControlError as exc:
                if exc.code not in {
                    "device_timeout_outcome_unknown", "device_call_failed_outcome_unknown",
                    "device_connection_changed",
                }:
                    raise
                await self._confirm_round_wallpaper_after_restart(selected, reboot_connection)
            return {**selected, "state": "rollback_restarting", "operation_id": uuid4().hex}

    async def deactivate_round_wallpaper(self):
        """保留已校验壁纸槽，只清除活动指针以显示几何皮肤。"""

        if self.operation_lock.locked():
            raise ControlError("control_busy")
        async with self.operation_lock:
            selected = validate_wallpaper_result(await self._call(
                self._connection(), DEACTIVATE_ROUND_WALLPAPER_TOOL,
                {"wallpaper_api": 1},
            ), "deactivation_pending_restart")
            reboot_connection = self._connection()
            try:
                if await self._call(reboot_connection, REBOOT_TOOL, {}) is not True:
                    raise ControlError("round_wallpaper_restart_not_acknowledged", 502)
            except ControlError as exc:
                if exc.code not in {
                    "device_timeout_outcome_unknown", "device_call_failed_outcome_unknown",
                    "device_connection_changed",
                }:
                    raise
                await self._confirm_skin_mode_after_restart(reboot_connection)
            return {**selected, "state": "skin_mode_restarting", "operation_id": uuid4().hex}

    async def _confirm_skin_mode_after_restart(self, previous_connection):
        """重启回执不确定时，要求新连接明确报告壁纸未激活且仍可恢复。"""

        deadline = asyncio.get_running_loop().time() + WALLPAPER_RESTART_CONFIRM_SECONDS
        transient = {
            "device_offline", "device_not_ready", "tools_not_ready",
            "device_connection_changed", "device_timeout_outcome_unknown",
            "device_call_failed_outcome_unknown",
        }
        while asyncio.get_running_loop().time() < deadline:
            try:
                connection = self._connection()
                if connection is previous_connection:
                    await asyncio.sleep(0.5)
                    continue
                status = validate_wallpaper_status(await self._call(
                    connection, GET_ROUND_WALLPAPER_TOOL, {}, timeout=self.timeout,
                ))
            except ControlError as exc:
                if exc.code in transient:
                    await asyncio.sleep(0.5)
                    continue
                raise
            if not status["active_valid"] and status["rollback_available"]:
                return status
            raise ControlError("round_wallpaper_readback_mismatch", 502)
        raise ControlError("device_timeout_outcome_unknown", 504)

    async def _confirm_round_wallpaper_after_restart(self, selected, previous_connection):
        """重启回执不确定时，仅用新连接的活动槽做最终确认，不重发写操作。"""
        deadline = asyncio.get_running_loop().time() + WALLPAPER_RESTART_CONFIRM_SECONDS
        transient = {
            "device_offline", "device_not_ready", "tools_not_ready",
            "device_connection_changed", "device_timeout_outcome_unknown",
            "device_call_failed_outcome_unknown",
        }
        while asyncio.get_running_loop().time() < deadline:
            try:
                connection = self._connection()
                if connection is previous_connection:
                    await asyncio.sleep(0.5)
                    continue
                status = validate_wallpaper_status(await self._call(
                    connection, GET_ROUND_WALLPAPER_TOOL, {}, timeout=self.timeout,
                ))
            except ControlError as exc:
                if exc.code in transient:
                    await asyncio.sleep(0.5)
                    continue
                raise
            expected = {
                "active_slot": selected["slot"],
                "active_wallpaper_id": selected["wallpaper_id"],
                "active_sha256": selected["sha256"],
                "active_size_bytes": selected["size_bytes"],
            }
            if status["active_valid"] and all(status[key] == value for key, value in expected.items()):
                return status
            raise ControlError("round_wallpaper_readback_mismatch", 502)
        raise ControlError("device_timeout_outcome_unknown", 504)

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
