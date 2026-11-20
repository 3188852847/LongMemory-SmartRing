"""仅向本机已确认的 QQ 私聊开放共享记忆。"""
import asyncio
import hashlib
import hmac
import json
from uuid import NAMESPACE_URL, uuid5

from aiohttp import web


def qq_token(directory):
    try:
        key = (directory / "console-plugin.key").read_text("utf-8").strip()
    except FileNotFoundError:
        return None
    return hmac.digest(key.encode(), b"qq-memory-v1", "sha256").hex() if key else None


def register_qq_memory(app, runtime, directory):
    binding = directory / "data/plugin_data/astrbot_plugin_private_companion/setup/binding.json"

    async def exchange(request):
        try:
            body = await request.clone(client_max_size=128000).json()
            if not isinstance(body, dict):
                raise ValueError
            platform, sender, message, role, text = (body[k] for k in
                ("platform", "sender", "message", "role", "text"))
            if (not all(isinstance(v, str) and 0 < len(v) <= 256 for v in (platform, sender, message))
                    or role not in ("user", "assistant") or not isinstance(text, str)
                    or not text.strip() or len(text) > 16000):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise web.HTTPBadRequest()
        try:
            owner = json.loads(binding.read_text("utf-8"))
        except (OSError, ValueError):
            owner = {}
        if not (isinstance(owner, dict) and owner.get("schema_version") == 2 and owner.get("confirmed") is True
                and platform == owner.get("platform_id") == owner.get("account_id")
                and sender == owner.get("participant_id")):
            raise web.HTTPForbidden()
        session = "qq-" + hashlib.sha256(json.dumps([platform, sender]).encode()).hexdigest()[:32]
        event_id = str(uuid5(NAMESPACE_URL, json.dumps([session, message, role])))
        try:
            context = await asyncio.to_thread(runtime.external_text, role, text, event_id=event_id, session_id=session)
        except ValueError:
            raise web.HTTPConflict()
        return web.json_response({"context": context})

    app.router.add_post("/api/internal/qq-memory", exchange)
