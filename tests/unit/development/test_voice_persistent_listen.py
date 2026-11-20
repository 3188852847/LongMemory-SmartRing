"""在同一个持久连接上验证重新拾音及整轮静默。"""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi/voice_persistent_session.py"
spec = importlib.util.spec_from_file_location("voice_persistent_session_test", SCRIPT)
session = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session)


@pytest.fixture
def device(monkeypatch):
    clock = SimpleNamespace(seconds=1000)
    monkeypatch.setattr(session, "time", SimpleNamespace(time=lambda: clock.seconds))

    class Connection:
        _check_timeout = AsyncMock()

    class ListenHandler:
        async def handle(self, conn, msg_json):
            conn.upstream(msg_json)

    # SDK 的注册表在启动时创建处理器实例，收到消息时才查找实例的 handle 方法。
    handler = ListenHandler()
    receive = SimpleNamespace(no_voice_close_connect=AsyncMock())
    session.install_persistent_device_session(Connection, receive, ListenHandler)
    conn = Connection()
    conn.features = {"persistent_session": True}
    conn.last_activity_time = 0
    conn.config = {"close_connection_no_voice_time": 5}
    conn.websocket = SimpleNamespace(send=AsyncMock())
    conn.logger = Mock()
    conn.upstream = Mock()
    return clock, conn, handler, receive


def test_two_silent_listens_each_get_one_full_window(device):
    clock, conn, handler, receive = device
    start = {"type": "listen", "state": "start", "mode": "auto"}
    for wake_at in (1000, 2000):
        clock.seconds = wake_at
        asyncio.run(handler.handle(conn, start))
        assert not conn._longmemory_session_idle
        assert conn.last_activity_time == wake_at * 1000
        previous = conn.websocket.send.await_count
        clock.seconds += 5
        asyncio.run(receive.no_voice_close_connect(conn, False))
        assert conn.websocket.send.await_count == previous
        clock.seconds += 1
        asyncio.run(receive.no_voice_close_connect(conn, False))
        asyncio.run(receive.no_voice_close_connect(conn, False))
        assert conn._longmemory_session_idle
        assert conn.websocket.send.await_count == previous + 1
    assert conn.websocket.send.await_args_list == [call(session.IDLE_MESSAGE)] * 2
    assert conn.upstream.call_args_list == [call(start)] * 2


@pytest.mark.parametrize(
    ("capable", "state"), [(True, "stop"), (True, "detect"), (False, "start")]
)
def test_other_listen_events_keep_upstream_state(device, capable, state):
    _, conn, handler, _ = device
    conn.features = {"persistent_session": capable}
    conn._longmemory_session_idle = True
    message = {"type": "listen", "state": state}
    asyncio.run(handler.handle(conn, message))
    conn.upstream.assert_called_once_with(message)
    assert conn._longmemory_session_idle
    assert conn.last_activity_time == 0


def test_wake_while_previous_idle_is_being_sent(device):
    clock, conn, handler, receive = device
    start = {"type": "listen", "state": "start"}

    async def exercise():
        await handler.handle(conn, start)
        clock.seconds += 6

        # 模拟发送协程让出事件循环后，SDK 已处理第二次唤醒。
        async def wake_during_send(_value):
            await handler.handle(conn, start)

        conn.websocket.send.side_effect = wake_during_send
        await receive.no_voice_close_connect(conn, False)
        assert not conn._longmemory_session_idle
        conn.websocket.send.side_effect = None
        clock.seconds += 6
        await receive.no_voice_close_connect(conn, False)
        assert conn._longmemory_session_idle

    asyncio.run(exercise())
    assert conn.websocket.send.await_args_list == [call(session.IDLE_MESSAGE)] * 2
