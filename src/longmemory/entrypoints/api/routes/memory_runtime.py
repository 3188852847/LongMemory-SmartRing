"""只供同机小智进程使用的记忆 Runtime 接口。"""

import asyncio
from dataclasses import asdict

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
            "memory_processing": prepared.observation.processing_status,
            "memory_warning": prepared.observation.warning_code,
            "retrieval_strategy": prepared.support.retrieval_strategy,
            "retrieval_warning": prepared.support.warning_code,
            "memory_write_enabled": prepared.write_enabled,
            "memory_use_enabled": prepared.use_enabled,
            "scenario_use_enabled": prepared.scenario_use_enabled,
            "scenario_retrieved": [asdict(item) for item in prepared.scenarios],
        })

    app.router.add_get("/api/internal/memory/status", status, allow_head=False)
    app.router.add_post("/api/internal/memory/prepare", prepare)
