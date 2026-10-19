"""中立引擎管理 API；旧 L1 API 独立保留，安全中间件与权限共用。"""

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from uuid import uuid4

from aiohttp import web

from longmemory.methods.contracts import MemoryEvent, UnsupportedCapabilityError
from ..errors import MemoryAccessError
from ..method_management import invoke_hy_management
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.administration import HyManagementConflict, HyManagementUncertain


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
        except HyManagementConflict as error:
            return web.json_response({"error": str(error)}, status=409)
        except HyManagementUncertain:
            return web.json_response({"error": "hy_management_outcome_uncertain"}, status=503)
        except HyResponseError:
            return web.json_response({"error": "hy_management_unavailable"}, status=503)
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

    async def hy_workspace(request):
        if request.query:
            raise web.HTTPBadRequest()
        def read():
            target = selected()
            result = invoke_hy_management(target, "workspace")
            state = target.status()
            # 能力必须同时满足引擎、启动权限和当前写开关。
            return {**result, "correction": bool(result.get("correction") and allow_correction and state["write_enabled"]),
                "deletion": bool(result.get("deletion") and allow_delete and state["write_enabled"]),
                "write_enabled": state["write_enabled"], "use_enabled": state["use_enabled"]}
        return await invoke(read)

    async def hy_profile(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(lambda: invoke_hy_management(selected(), "profile"))

    async def hy_history(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(lambda: invoke_hy_management(selected(), "history", item_id=request.match_info["item_id"]))

    async def hy_operations(request):
        if set(request.query) - {"item_id", "limit", "offset"} or any(len(request.query.getall(k)) != 1 for k in request.query):
            raise web.HTTPBadRequest()
        try:
            limit, offset = int(request.query.get("limit", 25)), int(request.query.get("offset", 0))
        except ValueError:
            raise web.HTTPBadRequest() from None
        item_id = request.query.get("item_id")
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000 or (item_id is not None and not 1 <= len(item_id) <= 256):
            raise web.HTTPBadRequest()
        return await invoke(lambda: invoke_hy_management(selected(), "operations", item_id=item_id, limit=limit, offset=offset))

    async def hy_mutation(request, action):
        if request.query:
            raise web.HTTPBadRequest()
        if not (allow_correction if action == "correct" else allow_delete):
            return web.json_response({"error": "hy_management_write_disabled"}, status=403)
        fields = {"request_id", "revision", "content" if action == "correct" else "confirmation"}
        data = await body(request, fields)
        try:
            from uuid import UUID
            if str(UUID(data["request_id"])) != data["request_id"] or len(data["revision"]) != 64 or any(c not in "0123456789abcdef" for c in data["revision"]):
                raise ValueError()
        except ValueError:
            raise web.HTTPBadRequest() from None
        if action == "delete" and data["confirmation"] != "删除这条记忆":
            raise web.HTTPBadRequest()
        item_id = request.match_info["item_id"]
        # 来源 ID 由平台生成；HTTP 不得提供角色、事件 ID、时间或库路径。
        content = data["content"] if action == "correct" else f"删除这条记忆：{item_id}"
        source = MemoryEvent("hy-management:" + data["request_id"], "user", content, datetime.now(UTC))
        return await invoke(lambda: invoke_hy_management(selected(), action, item_id=item_id,
            request_id=data["request_id"], expected_revision=data["revision"], source=source,
            **({"content": data["content"]} if action == "correct" else {})))

    async def hy_correction(request):
        return await hy_mutation(request, "correct")

    async def hy_deletion(request):
        return await hy_mutation(request, "delete")

    app.router.add_get("/api/memory-engine", info, allow_head=False)
    app.router.add_get("/api/memory-engine/items", listing, allow_head=False)
    app.router.add_get("/api/memory-engine/items/{item_id}", detail, allow_head=False)
    app.router.add_delete("/api/memory-engine/items/{item_id}", deletion)
    app.router.add_post("/api/memory-engine/items/{item_id}/corrections", correction)
    app.router.add_get("/api/memory-engine/sources/{event_id}", source, allow_head=False)
    app.router.add_post("/api/memory-engine/sources/{event_id}/retry", retry)
    app.router.add_get("/api/memory-engine/hy/workspace", hy_workspace, allow_head=False)
    app.router.add_get("/api/memory-engine/hy/profile", hy_profile, allow_head=False)
    app.router.add_get("/api/memory-engine/hy/operations", hy_operations, allow_head=False)
    app.router.add_get("/api/memory-engine/hy/items/{item_id}/history", hy_history, allow_head=False)
    app.router.add_post("/api/memory-engine/hy/items/{item_id}/corrections", hy_correction)
    app.router.add_post("/api/memory-engine/hy/items/{item_id}/deletion", hy_deletion)
