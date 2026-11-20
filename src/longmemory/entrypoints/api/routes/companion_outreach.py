"""陪伴小屋决定何时联系；此处仅选择一个终端并记录结果。"""
import asyncio
from contextlib import closing
from datetime import UTC, datetime, timedelta
import hashlib
import json
import sqlite3
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from aiohttp import web

from longmemory.adapters.device_control.protocol import BridgeError
from .qq_memory import confirmed_owner


class OutreachDelivery:
    def __init__(self, runtime, directory, bridge):
        self.runtime = runtime
        self.database = directory / "data/smartring-outreach.sqlite3"
        self.bridge = bridge
        self.web_active_until = 0.0
        self.lock = asyncio.Lock()

    def connect(self):
        db = sqlite3.connect(self.database)
        db.execute("""CREATE TABLE IF NOT EXISTS delivery (
            contact TEXT PRIMARY KEY, batch TEXT NOT NULL, digest TEXT NOT NULL,
            channel TEXT NOT NULL, state TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS delivery_batch ON delivery(batch)")
        return db

    def archive(self, contact, channel, text):
        if text:
            self.runtime.external_text("assistant", text, session_id="outreach-" + channel,
                                       event_id=str(uuid5(NAMESPACE_URL, contact)))

    async def select_channel(self, body):
        if body.get("qq_only"):
            return "qq"
        if monotonic() < self.web_active_until:
            return "web"
        if body.get("screen_ok") and valid_announcement(body["text"]):
            try:
                status = await self.bridge.status()
                if status["announcement_ready"] and not status["user_session_active"]:
                    return "screen"
            except BridgeError:
                pass
        return "qq"

    async def deliver(self, body, owner):
        # QQ 凭据/窗口重绑后，即使接到相同外部编号也不沿用旧窗口回执。
        contact = delivery_key(owner, body["contact_id"])
        digest = hashlib.sha256(body["text"].encode()).hexdigest()
        async with self.lock:
            with closing(self.connect()) as db:
                row = db.execute("SELECT channel,state,digest FROM delivery WHERE contact=?", (contact,)).fetchone()
                if row:
                    channel, state, saved = row
                    if digest != saved:
                        raise web.HTTPConflict()
                    if body["action"] == "ack":
                        if channel != "qq":
                            raise web.HTTPConflict()
                        if state in {"claimed", "unknown", "accepted"}:
                            state = body["status"] if state != "accepted" or body["status"] == "delivered" else state
                            with db:
                                db.execute("UPDATE delivery SET state=? WHERE contact=?", (state, contact))
                    if channel == "web" and state == "claimed":
                        # 网页投递就是归档；同 event_id 重做可恢复上次写入中断。
                        await asyncio.to_thread(self.archive, contact, channel, body["text"])
                        with db:
                            db.execute("UPDATE delivery SET state='delivered' WHERE contact=?", (contact,))
                        return result(channel, "delivered")
                    if state in {"accepted", "delivered"}:
                        await asyncio.to_thread(self.archive, contact, channel, body["text"])
                    return result(channel, "unknown" if state == "claimed" else state)
                if body["action"] == "ack":
                    raise web.HTTPConflict()
                batch = delivery_key(owner, body["batch_id"])
                first = db.execute("SELECT channel,state FROM delivery WHERE batch=? ORDER BY rowid LIMIT 1",
                                   (batch,)).fetchone()
                expires = body["expires"]
                now = datetime.now(UTC)
                last_user = (await asyncio.to_thread(self.runtime.dialogue_activity))["last_user_at"]
                busy = (last_user and datetime.fromisoformat(last_user) >
                        now - timedelta(seconds=body["min_idle_seconds"]))
                suppressed = now >= expires or busy or (first and first[1] in {"not_sent", "unknown"})
                channel = first[0] if first else ("qq" if suppressed else await self.select_channel(body))
                if channel == "screen" and not valid_announcement(body["text"]):
                    suppressed = True
                state = "not_sent" if suppressed else "claimed"
                with db:
                    db.execute("INSERT INTO delivery VALUES(?,?,?,?,?)", (contact,batch,digest,channel,state))
                if suppressed:
                    return result(channel, state)
                if channel == "qq":
                    return result(channel, state, send_qq=True)
                if channel == "screen":
                    try:
                        await self.bridge.announce(body["text"], min(expires, now + timedelta(seconds=60)))
                        state = "accepted"
                    except BridgeError as error:
                        state = "not_sent" if error.code in {
                            "device_busy","device_offline","device_not_ready","announcement_expired",
                            "tts_not_ready","invalid_announcement"} else "unknown"
                else:
                    state = "delivered"
                if channel == "web":
                    # 只在共享聊天记录写入成功后认定网页消息已投递。
                    await asyncio.to_thread(self.archive, contact, channel, body["text"])
                with db:
                    db.execute("UPDATE delivery SET state=? WHERE contact=?", (state, contact))
                if state == "accepted":
                    await asyncio.to_thread(self.archive, contact, channel, body["text"])
                return result(channel, state)


def valid_announcement(text):
    return bool(text) and text == text.strip() and len(text) <= 80 and all(ord(ch) >= 32 for ch in text)


def delivery_key(owner, key):
    return hashlib.sha256(json.dumps([*owner, key]).encode()).hexdigest()


def result(channel, state, send_qq=False):
    return {"channel": channel, "state": state, "send_qq": send_qq}


def register_outreach(app, runtime, directory, bridge):
    delivery = OutreachDelivery(runtime, directory, bridge)

    async def dialogue(request):
        try:
            limit = int(request.query.get("limit", "60"))
            if not 1 <= limit <= 100:
                raise ValueError
            rows = await asyncio.to_thread(runtime.recent_dialogue, limit, before_id=request.query.get("before"))
        except (ValueError, LookupError):
            raise web.HTTPBadRequest()
        if request.query.get("active") == "1":
            delivery.web_active_until = monotonic() + 15
        return web.json_response({"messages": rows, "enabled": True})

    async def outreach(request):
        try:
            body = await request.clone(client_max_size=100000).json()
            if not isinstance(body, dict):
                raise ValueError
            owner = confirmed_owner(directory)
            if not owner or owner != (body.get("platform"), body.get("sender")):
                raise web.HTTPForbidden()
            action = body["action"]
            if action == "activity":
                return web.json_response(await asyncio.to_thread(runtime.dialogue_activity))
            if action == "context":
                query = body.get("query") or "用户近期提到、适合关心或跟进的事情"
                if not isinstance(query, str) or len(query) > 16000:
                    raise ValueError
                context = await asyncio.to_thread(runtime.outreach_context, query)
                return web.json_response({"context": context})
            if (action not in ("dispatch", "ack") or not isinstance(body["text"], str) or len(body["text"]) > 16000
                    or not isinstance(body["contact_id"], str) or not 0 < len(body["contact_id"]) <= 512):
                raise ValueError
            if action == "ack":
                if body["status"] not in {"delivered", "accepted", "unknown", "not_sent"}:
                    raise ValueError
            else:
                if not isinstance(body["batch_id"], str) or not 0 < len(body["batch_id"]) <= 512:
                    raise ValueError
                for name in ("screen_ok", "qq_only"):
                    if type(body[name]) is not bool:
                        raise ValueError
                if not body["text"].strip() and not body["qq_only"]:
                    raise ValueError
                body["min_idle_seconds"] = body.get("min_idle_seconds", 300)
                if type(body["min_idle_seconds"]) is not int or not 0 <= body["min_idle_seconds"] <= 31*86400:
                    raise ValueError
                body["expires"] = datetime.fromisoformat(body["expires_at"])
                if body["expires"].tzinfo is None:
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise web.HTTPBadRequest()
        return web.json_response(await delivery.deliver(body, owner))

    app.router.add_get("/api/companion/dialogue", dialogue, allow_head=False)
    app.router.add_post("/api/internal/companion-outreach", outreach)
