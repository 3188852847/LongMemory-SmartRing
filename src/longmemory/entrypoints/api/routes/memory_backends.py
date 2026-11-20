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

    app.router.add_get("/api/memory-backends", listing, allow_head=False)
