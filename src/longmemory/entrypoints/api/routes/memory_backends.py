"""圆屏记忆后端选择 API；不热切换、不访问各后端记忆内容。"""

from aiohttp import web


def register_memory_backend_routes(app, store, xiaozhi=None):
    async def listing(_request):
        if store is None:
            return web.json_response({"enabled": False})
        result = {"enabled": True, **store.describe()}
        if xiaozhi is not None:
            result["xiaozhi"] = await xiaozhi.describe()
        return web.json_response(result)

    async def select(request):
        if store is None or xiaozhi is None:
            return web.json_response({"error": "memory_backends_disabled"}, status=403)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"backend"}:
                raise ValueError("invalid_body")
            result = await xiaozhi.select(body["backend"])
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_memory_backend"}, status=400)
        return web.json_response({"enabled": True, **store.describe(), "xiaozhi": result})

    app.router.add_get("/api/memory-backends", listing, allow_head=False)
    app.router.add_put("/api/memory-backends/selection", select)
