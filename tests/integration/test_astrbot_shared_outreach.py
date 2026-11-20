"""Exercise the pinned private companion's real planner, writer, outbox and receipts offline."""
from pathlib import Path
import shutil
import subprocess
import sys



ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "local/runtime/companion"
UPSTREAM = COMPANION / "data/plugins/astrbot_plugin_private_companion"
TOOLS = ROOT / "scripts/development/astrbot"


def test_private_companion_shared_contact(tmp_path):
    import pytest
    if not UPSTREAM.is_dir():
        pytest.skip("requires installed private companion")
    sys.path.insert(0, str(TOOLS))
    try:
        from install_outreach import install
    finally:
        sys.path.pop(0)
    package = tmp_path / "plugin"
    shutil.copytree(UPSTREAM / "companion_v2", package / "companion_v2",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (package / "astrbot_host").mkdir()
    for name in ("account_recovery.py", "core_reply_maintenance.py"):
        shutil.copyfile(UPSTREAM / "astrbot_host" / name, package / "astrbot_host" / name)
    shutil.copyfile(UPSTREAM / "metadata.yaml", package / "metadata.yaml")
    install(package)
    install(package)
    subprocess.run([str(COMPANION / ".venv/Scripts/python.exe"), "-X", "utf8", str(Path(__file__)),
                    str(package)], check=True, cwd=tmp_path, timeout=75)


if __name__ == "__main__":
    import unittest
    from unittest.mock import patch

    sys.path[:0] = [sys.argv.pop(), str(UPSTREAM)]
    from companion_v2 import smartring_outreach as bridge
    from tests.proactive_support import ContactFixture

    class SharedContact(ContactFixture, unittest.IsolatedAsyncioTestCase):
        async def exercise(self, channel, state, send_qq):
            app = await self.enabled()
            actions = []

            async def exchange(identity, action, **fields):
                actions.append(action)
                if action == "context":
                    return {"context": "这是一条合成的跨端聊天记录"}
                if action == "ack":
                    self.assertEqual(fields["status"], "delivered")
                    return {}
                self.assertTrue(fields["screen_ok"])
                self.assertFalse(fields["qq_only"])
                return {"send_qq": send_qq, "channel": channel, "state": state}

            with patch.object(bridge, "identity_for", return_value={"platform": "test", "sender": "test"}), \
                 patch.object(bridge, "exchange", exchange):
                result = await self.contact(app)
                task = result.unwrap().task
                await self.delivery_state(app, task.task_id, "delivered" if send_qq else state)
            self.assertEqual(len(self.sent), int(send_qq))
            self.assertEqual(actions.count("dispatch"), 1)
            self.assertEqual(actions.count("ack"), int(send_qq))
            self.assertTrue(any(material.payload == "这是一条合成的跨端聊天记录"
                                for call in self.called for material in call.original.context.materials))

        async def test_web(self):
            await self.exercise("web", "delivered", False)

        async def test_screen(self):
            await self.exercise("screen", "accepted", False)

        async def test_qq(self):
            await self.exercise("qq", "claimed", True)

    from tests import test_proactive_two_stage as upstream

    class ScheduledContact(upstream.TwoStageJudgedContactTests):
        async def test_persona_review_still_runs_after_two_stage_writing(self):
            async def exchange(identity, action, **fields):
                if action == "context":
                    return {"context": "跨端上下文"}
                if action == "dispatch":
                    return {"send_qq": True, "channel": "qq", "state": "claimed"}
                return {}
            with patch.object(bridge, "identity_for", return_value={"platform": "test", "sender": "test"}), \
                 patch.object(bridge, "exchange", exchange):
                await super().test_persona_review_still_runs_after_two_stage_writing()
            shared = [c for c in self.called if any(m.payload == "跨端上下文" for m in c.original.context.materials)]
            self.assertEqual(len(shared), 3)

    from tests.contact_schedule_support import ContactScheduleFixture

    class SharedAnchor(ContactScheduleFixture, unittest.IsolatedAsyncioTestCase):
        async def test_web_start_screen_answer_without_native_input(self):
            app = await self.enabled()
            self.settings(app, {"automatic_enabled": True, "interval_seconds": 60, "idle_seconds": 60}).unwrap()
            context = self.contact_context()
            schedule = app.contact_schedule
            channel, message = "web", "1"
            at = self.clock.now().isoformat()
            actions = []

            async def exchange(identity, action, **fields):
                actions.append(action)
                if action == "activity":
                    return {"last_user_at": at, "last_user_id": message, "last_user_channel": channel, "completed_at": at}
                if action == "context":
                    return {"context": "合成网页记忆"}
                return {"send_qq": False, "channel": "web", "state": "delivered"}

            with patch.object(bridge, "identity_for", return_value={"platform": "test", "sender": "test"}), \
                 patch.object(bridge, "exchange", exchange):
                schedule.bind_context(context, "真实绑定时选中的合成人格")
                await bridge.refresh_activity(schedule)
                self.assertEqual(schedule.latest_conversation(context)["execution_path"], "shared")
                self.advance(app, 60)
                schedule.advance()
                await self.automatic_delivery(app)
                self.assertEqual(actions.count("dispatch"), 1)
                self.assertEqual(self.sent, [])
                self.advance(app, 10)
                self.assertEqual(app.proactive.history.interaction(context, self.clock.now())["contacts_since_last_input"], 1)
                channel, message, at = "screen", "2", self.clock.now().isoformat()
                schedule.smartring_next_poll = 0
                await bridge.refresh_activity(schedule)
                self.assertEqual(app.proactive.history.interaction(context, self.clock.now())["contacts_since_last_input"], 0)
                schedule.advance()
                self.assertEqual(actions.count("dispatch"), 1)

    unittest.main()
