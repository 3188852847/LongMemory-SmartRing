"""文字模式启动不能触发旧圆屏库的后台联系任务。"""

import asyncio
import sqlite3

from aiohttp import web

from longmemory.bootstrap import build_application
from longmemory.entrypoints.api import server


def test_text_mode_does_not_construct_or_run_round_screen_schedule(tmp_path, monkeypatch):
    database = tmp_path / "synthetic.db"
    application = build_application(database_path=database)
    application.close()
    before = database.read_bytes()

    def unexpected_schedule(*args, **kwargs):
        raise AssertionError("文字模式不应构造圆屏定时任务")

    monkeypatch.setattr(server, "ProactiveScheduleLoop", unexpected_schedule)

    async def run():
        app = server.create_app(database=database, proactive_schedule_enabled=False)
        runner = web.AppRunner(app)
        try:
            await runner.setup()
            await asyncio.sleep(0)
        finally:
            await runner.cleanup()

    asyncio.run(run())
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM proactive_outreach").fetchone()[0] == 0
