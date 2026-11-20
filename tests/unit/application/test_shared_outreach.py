"""跨端共用一次原插件投递许可；合成设备、QQ 和个人绑定。"""
import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic
from unittest.mock import Mock

from longmemory.adapters.device_control.protocol import BridgeError
from longmemory.entrypoints.api.routes.companion_outreach import OutreachDelivery


def test_dispatch_and_replay_across_channels(tmp_path):
    class Screen:
        calls = 0
        ready = True
        timeout = False

        async def status(self):
            return {"announcement_ready": self.ready, "user_session_active": False}

        async def announce(self, text, deadline):
            self.calls += 1
            if self.timeout:
                raise BridgeError("bridge_timeout")

    async def run():
        (tmp_path / "data").mkdir()
        runtime, screen = Mock(), Screen()
        runtime.dialogue_activity.return_value = {"last_user_at": None}
        delivery = OutreachDelivery(runtime, tmp_path, screen)
        owner = ("synthetic-qq", "synthetic-owner")
        def message(key, **extra):
            return dict(action="dispatch", contact_id=key, batch_id=key, text="最近的茶喝得怎么样？",
                        min_idle_seconds=300, expires=datetime.now(UTC)+timedelta(minutes=1),
                        **extra)
        web = message("web", screen_ok=True)
        delivery.web_active_until = monotonic()+30
        for _ in range(2):
            assert (await delivery.deliver(web, owner))["state"] == "delivered"
        assert len({c.kwargs["event_id"] for c in runtime.external_text.call_args_list}) == 1
        delivery.web_active_until = 0
        sound = message("screen", screen_ok=True)
        assert (await delivery.deliver(sound, owner))["state"] == "accepted"
        delivery = OutreachDelivery(runtime, tmp_path, screen)
        assert not (await delivery.deliver(sound, owner))["send_qq"]
        assert screen.calls == 1
        screen.timeout = True
        uncertain = message("unconfirmed", screen_ok=True)
        assert (await delivery.deliver(uncertain, owner))["state"] == "unknown"
        assert (await delivery.deliver(uncertain, owner))["state"] == "unknown"
        assert screen.calls == 2
        qq = message("qq", qq_only=True)
        results = await asyncio.gather(delivery.deliver(qq, owner), delivery.deliver(qq, owner))
        assert sum(r["send_qq"] for r in results) == 1
        ack = dict(qq, action="ack", status="delivered")
        assert (await delivery.deliver(ack, owner))["state"] == "delivered"
        assert runtime.external_text.call_args.kwargs["session_id"] == "outreach-qq"
        runtime.dialogue_activity.return_value = {"last_user_at": datetime.now(UTC).isoformat()}
        assert (await delivery.deliver(message("busy"), owner))["state"] == "not_sent"

    asyncio.run(run())
