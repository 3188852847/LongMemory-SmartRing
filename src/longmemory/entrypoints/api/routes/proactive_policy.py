"""本机控制台主动联系设置；保存设置本身不会创建或投递消息。"""

import asyncio

from aiohttp import web
from pydantic import ValidationError

from ..contracts import ProactivePolicyRequest
from ..memory_backend import MemoryAccessError


def register_proactive_policy_routes(app, backend):
    async def policy(request):
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(backend.proactive_policy)
            else:
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                try:
                    body = ProactivePolicyRequest.model_validate(await request.json())
                except (ValidationError, ValueError, UnicodeError):
                    raise web.HTTPBadRequest() from None
                result = await asyncio.to_thread(backend.update_proactive_policy, body)
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/proactive-policy", policy, allow_head=False)
    app.router.add_put("/api/proactive-policy", policy)
