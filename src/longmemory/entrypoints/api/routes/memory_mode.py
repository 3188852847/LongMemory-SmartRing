"""本机控制台的运行期记忆模式；不持久化、不删除数据。"""

import asyncio
from dataclasses import asdict

from aiohttp import web
from pydantic import ValidationError

from longmemory.entrypoints.api.contracts import ExplicitMemoryRequest


def register_memory_mode_routes(app, backend):
    async def mode(request):
        if backend is None:
            return web.json_response({"error": "chat_not_enabled"}, status=503)
        runtime = backend.memory_runtime()
        if request.method == "GET":
            status = await asyncio.to_thread(runtime.status)
        else:
            if request.content_type != "application/json":
                raise web.HTTPBadRequest()
            try:
                body = await request.json()
            except (ValueError, UnicodeError):
                raise web.HTTPBadRequest() from None
            allowed = {"write_enabled", "use_enabled", "scenario_use_enabled", "persona_use_enabled"}
            if (not isinstance(body, dict)
                    or not {"write_enabled", "use_enabled"} <= set(body)
                    or not set(body) <= allowed
                    or type(body["write_enabled"]) is not bool
                    or type(body["use_enabled"]) is not bool
                    or ("scenario_use_enabled" in body and type(body["scenario_use_enabled"]) is not bool)
                    or ("persona_use_enabled" in body and type(body["persona_use_enabled"]) is not bool)):
                raise web.HTTPBadRequest()
            status = await asyncio.to_thread(
                runtime.configure,
                write_enabled=body["write_enabled"],
                use_enabled=body["use_enabled"],
                scenario_use_enabled=body.get("scenario_use_enabled"),
                persona_use_enabled=body.get("persona_use_enabled"),
            )
        return web.json_response({
            "write_enabled": status["write_enabled"],
            "use_enabled": status["use_enabled"],
            "scenario_use_enabled": status["scenario_use_enabled"],
            "scenario_available": status["scenario_available"],
            "persona_use_enabled": status["persona_use_enabled"],
            "persona_available": status["persona_available"],
            "persistent": status["settings_persistent"],
            "l0_archived_when_write_disabled": True,
        })

    app.router.add_get("/api/memory-mode", mode, allow_head=False)
    app.router.add_put("/api/memory-mode", mode)

    async def explicit_memory(request):
        """从管理页明确写入一条事实，但不创建第二套数据库写入路径。"""

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
