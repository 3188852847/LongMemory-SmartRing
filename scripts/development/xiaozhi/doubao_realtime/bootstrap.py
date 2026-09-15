"""只在本进程安装实时模式钩子，不修改固定 Xiaozhi 上游文件。

保留上游认证、hello/MCP、设备连接与发送节拍，完整绕过本地 VAD、ASR、
LLM、TTS 和记忆加载。原三段式启动不导入或安装本模块。
"""

import asyncio
import json
import sys

from .bridge import RealtimeBridge


class _ConnectionLogger:
    """固定上游会记录完整握手头；实时模式屏蔽该条日志中的认证信息。"""
    def __init__(self, logger):
        self.logger = logger

    def bind(self, *args, **kwargs):
        return _ConnectionLogger(self.logger.bind(*args, **kwargs))

    def info(self, message, *args, **kwargs):
        if isinstance(message, str) and " conn - Headers:" in message:
            message, args, kwargs = "圆屏连接已建立；握手头不记录", (), {}
        return self.logger.info(message, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.logger, name)


def install_realtime_mode(connection_class, realtime_config, *, client_factory=None,
                          encoder_factory=None):
    if getattr(connection_class, "_doubao_realtime_installed", False):
        return
    from core import websocket_server
    from core.handle.sendAudioHandle import sendAudio, send_tts_message
    if client_factory is None:
        from .client import DoubaoRealtimeClient
        client_factory = DoubaoRealtimeClient
    if encoder_factory is None:
        from core.utils.opus_encoder_utils import OpusEncoderUtils
        encoder_factory = lambda: OpusEncoderUtils(24000, 1, 60)

    # WebSocketServer 构造函数在第一台设备连接前就加载共享模型。仅替换
    # 连接级初始化无法避免FunASR驻留；这个进程只运行一个明确选定的模式。
    websocket_server.initialize_modules = lambda *args, **kwargs: {}
    connection_module = sys.modules.get("core.connection")
    if connection_module is not None:
        # 即便跳过模型初始化，上游构造器仍会读旧prompt_template文件。
        # 实时客户端只使用专属dotenv的instructions，不加载旧三段式提示。
        connection_module.PromptManager = lambda *args, **kwargs: None
    original_init = connection_class.__init__
    original_route = connection_class._route_message
    original_close = connection_class.close
    original_clear = connection_class.clear_queues

    def initialize_connection(connection, *args, **kwargs):
        original_init(connection, *args, **kwargs)
        connection.voice_mode = "doubao_realtime"
        connection.logger = _ConnectionLogger(connection.logger)

    async def initialize(connection):
        connection._doubao_initialization_task = asyncio.current_task()
        connection._doubao_ready_event = asyncio.Event()
        connection.voice_mode = "doubao_realtime"
        try:
            allowed = str(connection.config.get("Memory", {}).get("LongMemory", {})
                          .get("allowed_device_id", "")).lower()
            if not allowed or str(connection.device_id).lower() != allowed:
                await connection.close()
                return
            # 配置校验要求本地模式，仍复用上游绑定状态事件，保持路由边界。
            await connection._initialize_private_config_async()
            if connection.need_bind:
                await connection.close()
                return
            connection.vad = connection.asr = connection.llm = connection.tts = None
            connection.memory = connection.intent = None
            connection.sample_rate = 24000
            connection._doubao_bridge = RealtimeBridge(
                connection, client_factory(realtime_config), encoder_factory(),
                audio_sender=sendAudio, state_sender=send_tts_message,
            )
            await connection._doubao_bridge.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 云端异常可能包含响应体或认证头；只保留固定错误码。
            connection._doubao_failure_code = "realtime_initialization_failed"
            connection.logger.bind(tag="doubao-realtime").error("实时语音初始化失败")
            bridge = getattr(connection, "_doubao_bridge", None)
            if bridge is not None:
                bridge.failure_code = "realtime_initialization_failed"
                await bridge.close()
            await connection.close()
        finally:
            connection._doubao_ready_event.set()

    async def ready_bridge(connection):
        event = getattr(connection, "_doubao_ready_event", None)
        if event is not None and not event.is_set():
            try:
                await asyncio.wait_for(event.wait(), timeout=15)
            except asyncio.TimeoutError:
                return None
        bridge = getattr(connection, "_doubao_bridge", None)
        return bridge if bridge is not None and bridge.ready else None

    async def route(connection, message):
        # 原认证由WebSocketServer在创建ConnectionHandler前执行；这里还保留
        # 连接绑定门槛，不能为了绕过ASR空值检查而直接接受未绑定音频。
        if not connection.bind_completed_event.is_set():
            try:
                await asyncio.wait_for(connection.bind_completed_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                return
        if connection.need_bind:
            return
        if isinstance(message, bytes):
            bridge = await ready_bridge(connection)
            if bridge is None or not message or len(message) > 8208:
                return
            if connection.conn_from_mqtt_gateway:
                # MQTT具有另一种16字节头，不能交给direct_ws_v2再解包。
                if len(message) < 17:
                    return
                timestamp = int.from_bytes(message[8:12], "big")
                pcm = connection._decode_opus_packet(message[16:])
                if pcm and timestamp > 0 and connection.client_aec:
                    pcm = connection._apply_aec(timestamp, pcm)
            else:
                pcm = connection._decode_opus_packet(message)
            if pcm:
                await bridge.accept_pcm(pcm)
            return
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
            except (ValueError, TypeError):
                return
            if not isinstance(parsed, dict):
                return
            kind = parsed.get("type")
            if kind in {"listen", "abort"}:
                bridge = await ready_bridge(connection)
                if bridge is not None:
                    try:
                        if kind == "abort":
                            await bridge.interrupt()
                        else:
                            await bridge.listen(parsed.get("state"), parsed.get("mode"), parsed.get("text"))
                    except Exception:
                        await bridge._fail("realtime_control_failed")
                return
            if kind == "hello":
                params = parsed.get("audio_params", {})
                if (not isinstance(params, dict) or params.get("format") != "opus"
                        or params.get("channels", 1) != 1
                        or params.get("frame_duration", 60) != 60):
                    await connection.close()
                    return
                # 上传Opus固定解码到16k PCM；下行编码是云端24k PCM，hello回复
                # 必须告知终端真实下行采样率。MCP/AEC特性仍由原hello处理。
                parsed["audio_params"] = dict(params, sample_rate=24000, channels=1,
                                               frame_duration=60)
                message = json.dumps(parsed, ensure_ascii=False)
        return await original_route(connection, message)

    def clear(connection):
        bridge = getattr(connection, "_doubao_bridge", None)
        if bridge is not None:
            bridge.reset_output()
        return original_clear(connection)

    async def close(connection, ws=None):
        task = getattr(connection, "_doubao_initialization_task", None)
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        bridge = getattr(connection, "_doubao_bridge", None)
        if bridge is not None:
            await bridge.close()
        return await original_close(connection, ws)

    async def save_and_close(connection, ws):
        # 备用模式不把云端会话写入个人记忆，也不触发上游标题/记忆保存线程。
        await connection.close(ws)

    connection_class.__init__ = initialize_connection
    connection_class._background_initialize = initialize
    connection_class._route_message = route
    connection_class.clear_queues = clear
    connection_class.close = close
    connection_class._save_and_close = save_and_close
    connection_class._doubao_realtime_installed = True
