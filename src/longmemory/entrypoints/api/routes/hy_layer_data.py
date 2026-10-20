"""只接受固定层/有界页；沿用会话鉴权，不提供任意SDK调用或数据路径。"""

import asyncio

from aiohttp import web

from longmemory.methods.contracts import UnsupportedCapabilityError
from longmemory.methods.hy_memory.layer_data import validate_page, identifier, HyLayerDataBusy
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from ..method_management import invoke_hy_management


def register_hy_layer_data_routes(app, runtime_provider):
    async def read(operation, arguments):
        def invoke():
            runtime = runtime_provider()
            if runtime is None:
                raise HyResponseError("hy_layer_data_unavailable")
            return invoke_hy_management(runtime, operation, **arguments)
        try:
            return web.json_response(await asyncio.to_thread(invoke))
        except HyLayerDataBusy:
            return web.json_response({"error": "hy_layer_data_busy"}, status=503)
        except UnsupportedCapabilityError:
            return web.json_response({"error": "memory_backend_capability_unsupported"}, status=501)
        except LookupError:
            return web.json_response({"error": "hy_layer_item_not_found"}, status=404)
        except (HyResponseError, RuntimeError, ValueError, TypeError, KeyError):
            return web.json_response({"error": "hy_layer_data_unavailable"}, status=503)

    async def page(request):
        if (request.can_read_body or set(request.query) - {"limit", "offset", "state"}
                or any(len(request.query.getall(key)) != 1 for key in request.query)):
            raise web.HTTPBadRequest()
        try:
            arguments = {"layer": request.match_info["layer"],
                         "limit": int(request.query.get("limit", 20)),
                         "offset": int(request.query.get("offset", 0)), "state": request.query.get("state", "all")}
            validate_page(**arguments)
        except ValueError:
            raise web.HTTPBadRequest() from None
        return await read("layer_page", arguments)

    async def detail(request):
        if request.can_read_body or request.query:
            raise web.HTTPBadRequest()
        arguments = {"layer": request.match_info["layer"], "item_id": request.match_info["item_id"]}
        try:
            validate_page(arguments["layer"])
            identifier(arguments["item_id"])
        except ValueError:
            raise web.HTTPBadRequest() from None
        return await read("layer_detail", arguments)

    app.router.add_get("/api/memory-engine/hy/layers/{layer}", page, allow_head=False)
    app.router.add_get("/api/memory-engine/hy/layers/{layer}/items/{item_id}", detail, allow_head=False)
