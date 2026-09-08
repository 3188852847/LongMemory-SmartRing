"""圆屏皮肤档案 API；当前只管理网页预览选择，不向真机下发。"""

from aiohttp import web


def register_round_skin_routes(app, store):
    async def listing(_request):
        try:
            return web.json_response({"enabled": True, **store.describe()})
        except (OSError, ValueError, UnicodeError):
            return web.json_response({"error": "round_skins_unavailable"}, status=503)

    async def select(request):
        try:
            if request.content_type != "application/json":
                raise ValueError("invalid_body")
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"skin_id"} or not isinstance(body["skin_id"], str):
                raise ValueError("invalid_body")
            return web.json_response({"enabled": True, **store.select(body["skin_id"])})
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_round_skin"}, status=400)

    app.router.add_get("/api/round-skins", listing, allow_head=False)
    app.router.add_put("/api/round-skins/selection", select)
