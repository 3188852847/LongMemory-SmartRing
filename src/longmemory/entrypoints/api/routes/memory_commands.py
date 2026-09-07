"""本机所有者发起的明确记忆命令；不承载普通聊天或直接 SQL 写入。"""

import asyncio
from dataclasses import asdict

from aiohttp import web
from pydantic import ValidationError

from longmemory.entrypoints.api.contracts import ExplicitMemoryRequest


def register_memory_command_routes(app, backend):
    async def explicit_memory(request):
        """从管理页明确写入一条事实，并复用圆屏相同的应用层契约。"""

        if backend is None:
            return web.json_response({"error": "chat_not_enabled"}, status=503)
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ExplicitMemoryRequest.model_validate(await request.json())
        except (ValidationError, ValueError, TypeError, UnicodeError):
            return web.json_response({"error": "invalid_explicit_memory"}, status=400)
        prepared = await asyncio.to_thread(
            backend.memory_runtime().prepare_user,
            f"请记住：{body.content}",
        )
        command = prepared.memory_command
        if command is None or command.kind != "include":
            return web.json_response({"error": "explicit_memory_not_handled"}, status=409)
        return web.json_response({
            **asdict(command),
            "l0_message_id": prepared.event.event_id,
        })

    app.router.add_post("/api/memory-commands/include", explicit_memory)
