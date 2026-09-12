"""L2 证据充分性影子记录的本机只读 HTTP 入口。"""

import asyncio
import re

from aiohttp import web


def register_l2_sufficiency_shadow_routes(app, backend):
    async def listing(request):
        if set(request.query) - {"limit"} or any(
            len(request.query.getall(key)) != 1 for key in request.query
        ):
            raise web.HTTPBadRequest()
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        if not 1 <= limit <= 100:
            raise web.HTTPBadRequest()
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=503)
        return web.json_response(await asyncio.to_thread(
            backend.list_l2_sufficiency_shadow, limit=limit,
        ))

    async def detail(request):
        message_id = request.match_info["message_id"]
        if (not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", message_id)
                or backend is None):
            if backend is None:
                return web.json_response({"error": "chat_disabled"}, status=503)
            raise web.HTTPBadRequest()
        value = await asyncio.to_thread(
            backend.get_l2_sufficiency_shadow, message_id,
        )
        if value is None:
            return web.json_response(
                {"error": "l2_sufficiency_shadow_not_found"}, status=404,
            )
        return web.json_response(value)

    app.router.add_get(
        "/api/l2-sufficiency-shadow", listing, allow_head=False,
    )
    app.router.add_get(
        "/api/l2-sufficiency-shadow/{message_id}", detail, allow_head=False,
    )
