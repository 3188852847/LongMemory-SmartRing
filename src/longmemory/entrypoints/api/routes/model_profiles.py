"""本机模型配置档 API；读取响应绝不包含密钥。"""

from aiohttp import web


def register_model_profile_routes(app, store):
    async def listing(_request):
        if store is None:
            return web.json_response({"enabled": False})
        return web.json_response({"enabled": True, **store.describe()})

    async def save(request):
        if store is None:
            return web.json_response({"error": "model_profiles_disabled"}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"error": "invalid_body"}, status=400)
        try:
            result = store.save(request.match_info["profile"], await request.json())
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_model_profile"}, status=400)
        return web.json_response({"enabled": True, **result})

    app.router.add_get("/api/model-profiles", listing, allow_head=False)
    app.router.add_put("/api/model-profiles/{profile}", save)
