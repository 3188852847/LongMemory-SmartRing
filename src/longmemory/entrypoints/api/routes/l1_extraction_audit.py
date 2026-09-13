"""日常 L1 提取账本的本机只读 HTTP 入口。"""

import asyncio

from aiohttp import web


def register_l1_extraction_audit_routes(app, backend):
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
            backend.list_l1_extraction_audit, limit=limit,
        ))

    app.router.add_get(
        "/api/l1-extraction-audit", listing, allow_head=False,
    )
