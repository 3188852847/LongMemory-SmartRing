"""只供同机小智进程使用的记忆 Runtime 接口。"""

import asyncio

from aiohttp import web

from longmemory.entrypoints.xiaozhi.mapping import extract_user_text


def register_memory_runtime_routes(app, backend):
    if backend is None:
        return

    async def status(_request):
        result = await asyncio.to_thread(backend.memory_runtime().status)
        return web.json_response({"version": 1, **result})

    async def prepare(request):
        request = request.clone(client_max_size=32768)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"version", "query"} or body.get("version") != 1:
                raise ValueError
            text = extract_user_text(body.get("query"))
        except (ValueError, TypeError, UnicodeError):
            return web.json_response({"error": "invalid_memory_request", "version": 1}, status=400)
        prepared = await asyncio.to_thread(backend.memory_runtime().prepare_user, text)
        return web.json_response({
            "version": 1,
            "context": prepared.support.context,
            "turn_id": prepared.event.event_id,
            "added": sum(item.operation == "add" for item in prepared.observation.writes),
            "retrieved": len(prepared.support.retrieved),
        })

    app.router.add_get("/api/internal/memory/status", status, allow_head=False)
    app.router.add_post("/api/internal/memory/prepare", prepare)
