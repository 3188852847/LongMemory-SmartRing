"""中立引擎管理 API；旧 L1 API 独立保留，安全中间件与权限共用。"""

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from uuid import uuid4

from aiohttp import web

from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from ..errors import MemoryAccessError


def _json(value):
    if is_dataclass(value):
        return _json(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def register_memory_engine_routes(app, runtime, *, allow_delete=False, allow_correction=False):
    async def invoke(function, *args, **kwargs):
        try:
            return web.json_response(_json(await asyncio.to_thread(function, *args, **kwargs)))
        except UnsupportedCapabilityError:
            return web.json_response({"error": "memory_backend_capability_unsupported"}, status=501)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)
        except LookupError:
            return web.json_response({"error": "memory_item_or_source_not_found"}, status=404)
        except ValueError:
            return web.json_response({"error": "memory_operation_rejected"}, status=409)

    def selected():
        if runtime is None:
            raise MemoryAccessError("memory_runtime_unavailable", 503)
        return runtime() if callable(runtime) else runtime

    async def info(_request):
        def state():
            result = selected().status()
            caps = result["management_capabilities"]
            return {**result, "allow_delete": allow_delete and caps.get("deletion", False),
                    "allow_correction": allow_correction and caps.get("correction", False)}
        return await invoke(state)

    async def listing(request):
        if set(request.query) - {"q", "state", "limit", "offset"} or any(
            len(request.query.getall(key)) != 1 for key in request.query
        ):
            raise web.HTTPBadRequest()
        try:
            limit, offset = int(request.query.get("limit", 25)), int(request.query.get("offset", 0))
        except ValueError:
            raise web.HTTPBadRequest() from None
        query, state = request.query.get("q", ""), request.query.get("state", "active")
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000 or len(query) > 200 or not 1 <= len(state) <= 40:
            raise web.HTTPBadRequest()
        return await invoke(lambda: selected().administer("listing", "list_items",
            query=query, state=state, limit=limit, offset=offset))

    async def body(request, fields):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            value = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if not isinstance(value, dict) or set(value) != fields or any(
            not isinstance(item, str) or not item.strip() or len(item) > 1000
            for item in value.values()
        ):
            raise web.HTTPBadRequest()
        return value

    async def detail(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(lambda: selected().administer("detail", "get_item", request.match_info["item_id"]))

    async def correction(request):
        if not allow_correction:
            return web.json_response({"error": "memory_correction_disabled"}, status=403)
        data = await body(request, {"content", "revision"})
        source = MemoryEvent(str(uuid4()), "user", data["content"], datetime.now(UTC))
        return await invoke(lambda: selected().administer("correction", "correct_item",
            request.match_info["item_id"], data["content"], expected_revision=data["revision"], source=source))

    async def deletion(request):
        if not allow_delete:
            return web.json_response({"error": "memory_read_only"}, status=403)
        data = await body(request, {"revision"})
        def remove():
            selected().administer("deletion", "delete_item", request.match_info["item_id"], expected_revision=data["revision"])
            return {"deleted": True, "platform_sources_preserved": True}
        return await invoke(remove)

    async def source(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(lambda: selected().source_detail(request.match_info["event_id"]))

    async def retry(request):
        if not allow_correction:
            return web.json_response({"error": "memory_correction_disabled"}, status=403)
        data = await body(request, {"expected_attempt_id"})
        return await invoke(lambda: selected().retry_source(request.match_info["event_id"], **data))

    app.router.add_get("/api/memory-engine", info, allow_head=False)
    app.router.add_get("/api/memory-engine/items", listing, allow_head=False)
    app.router.add_get("/api/memory-engine/items/{item_id}", detail, allow_head=False)
    app.router.add_delete("/api/memory-engine/items/{item_id}", deletion)
    app.router.add_post("/api/memory-engine/items/{item_id}/corrections", correction)
    app.router.add_get("/api/memory-engine/sources/{event_id}", source, allow_head=False)
    app.router.add_post("/api/memory-engine/sources/{event_id}/retry", retry)
