"""中立的导航身份；provider只能窥视已存在对象，不能调用懒初始化入口。"""

import asyncio

from aiohttp import web


def register_memory_identity_route(app, runtime_provider):
    def read():
        runtime = runtime_provider()
        if runtime is not None:
            return runtime.identity()
        return {"schema_version": 1, "configured": False, "method": None,
                "representation": None, "legacy_sqlite": None, "state": "unconfigured"}

    async def identity(request):
        if request.query or request.can_read_body:
            raise web.HTTPBadRequest()
        try:
            return web.json_response(await asyncio.to_thread(read))
        except Exception as error:
            # 未配置是200明确状态；繁忙和关闭不能回退成旧引擎或冒称未配置。
            code = "memory_identity_busy" if isinstance(error, RuntimeError) and str(error) == "memory_identity_busy" else "memory_identity_unavailable"
            return web.json_response({"error": code}, status=503)

    app.router.add_get("/api/memory-engine/identity", identity, allow_head=False)
