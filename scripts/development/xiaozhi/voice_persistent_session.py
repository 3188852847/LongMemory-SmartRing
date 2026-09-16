"""让支持持久在线会话的圆屏结束采音后保留控制连接。"""

import asyncio
import json
import time


FEATURE = "persistent_session"
IDLE_MESSAGE = json.dumps(
    {"type": "session", "state": "idle"}, separators=(",", ":"),
)
HEARTBEAT_MESSAGE = json.dumps(
    {"type": "session", "state": "heartbeat"}, separators=(",", ":"),
)


def _supported(connection) -> bool:
    features = getattr(connection, "features", None)
    return isinstance(features, dict) and features.get(FEATURE) is True


def install_persistent_device_session(
    connection_class, receive_audio_module, *, heartbeat_seconds=45,
    feature_wait_seconds=10,
):
    """协商后把“结束采音”与“关闭 WebSocket”拆开。

    旧固件没有能力声明，继续走上游原逻辑。新固件在静默超时后收到一次
    ``session.idle``，回到待机并停止上传麦克风；服务端随后只发送无正文
    心跳，使控制连接可以承载主动交流并避免下次唤醒重新握手。
    """

    if getattr(connection_class, "_longmemory_persistent_session_installed", False):
        return
    if heartbeat_seconds <= 0 or feature_wait_seconds < 0:
        raise ValueError("persistent_session_interval_invalid")

    original_no_voice = receive_audio_module.no_voice_close_connect
    original_check_timeout = connection_class._check_timeout

    async def no_voice_close_connect(connection, have_voice):
        if not _supported(connection):
            return await original_no_voice(connection, have_voice)
        if have_voice:
            connection._longmemory_session_idle = False
            return await original_no_voice(connection, True)
        if getattr(connection, "close_after_chat", False):
            return None
        last_activity = getattr(connection, "last_activity_time", 0.0)
        if last_activity <= 0.0:
            return None
        timeout = int(connection.config.get("close_connection_no_voice_time", 120))
        if time.time() * 1000 - last_activity <= timeout * 1000:
            return None
        if getattr(connection, "_longmemory_session_idle", False):
            return None
        await connection.websocket.send(IDLE_MESSAGE)
        connection._longmemory_session_idle = True
        connection.logger.bind(tag="persistent-session").info(
            "圆屏静默会话已回到待机；控制连接保持在线"
        )
        return None

    async def check_timeout(connection):
        # 上游在 hello 之前创建超时任务，因此给能力协商一个有界等待窗口。
        deadline = time.monotonic() + feature_wait_seconds
        while getattr(connection, "features", None) is None:
            if time.monotonic() >= deadline or connection.stop_event.is_set():
                break
            await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if not _supported(connection):
            return await original_check_timeout(connection)

        try:
            while not connection.stop_event.is_set():
                await asyncio.sleep(heartbeat_seconds)
                if connection.stop_event.is_set():
                    break
                await connection.websocket.send(HEARTBEAT_MESSAGE)
                # 新固件会把 heartbeat 作为协议消息消费，不呈现给用户。这里不能
                # 改写 last_activity_time：它表示用户语音活动，空闲切换依赖该时间。
        except Exception:
            # WebSocket 主接收循环负责记录并释放断线；心跳不创建第二套重试。
            connection.logger.bind(tag="persistent-session").warning(
                "圆屏持久在线心跳发送失败；等待主连接循环清理"
            )
            return None
        finally:
            connection.logger.bind(tag="persistent-session").info(
                "圆屏持久在线心跳已退出"
            )

    receive_audio_module.no_voice_close_connect = no_voice_close_connect
    connection_class._check_timeout = check_timeout
    connection_class._longmemory_persistent_session_installed = True
