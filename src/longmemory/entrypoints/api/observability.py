"""HTTP 请求边界观察；保留认证和业务响应的原语义。"""

import asyncio
import json
import secrets
from aiohttp import web

from longmemory.infrastructure.logging.diagnostics import CODES, REQUEST_CONTEXT, log_inventory
from longmemory.infrastructure.logging.retention import retention_plan


def bind_voice_request(request):
    context = REQUEST_CONTEXT.get()
    if context is not None:
        observer, request_id = context
        try:
            observer.bind_voice(request_id, request.headers.get("X-Voice-Round-Id"))
        except Exception:
            pass  # 仅观测失败不得改变业务。


def operation_name(path):
    # 不使用客户端路径或参数作为字段。动态 UUID、查询正文及非法 URL 一律不记录。
    if path.startswith("/api/internal/memory/"):
        return "memory_runtime"
    for prefix, name in (("/api/chats", "chat"), ("/api/chat-config", "chat"),
                         ("/api/chat-model", "chat"), ("/api/chat-memory-feedback", "chat"),
                         ("/api/device", "device"),
                         ("/api/memories", "memory"), ("/api/observability", "diagnostics")):
        if path == prefix or path.startswith(prefix + "/"):
            return name
    return "console"


def observability_middleware(observer):
    @web.middleware
    async def observe(request, handler):
        # 摘要和静态资源不产生新条目，避免页面资源加载挤掉真正的故障。
        if request.path in {"/api/observability", "/api/internal/memory/voice-events"} or not request.path.startswith("/api/"):
            response = await handler(request)
            response.headers["X-Request-Id"] = secrets.token_hex(12)
            return response
        trace = observer.begin(operation_name(request.path), mutating=request.method not in {"GET", "HEAD", "OPTIONS"})
        token = REQUEST_CONTEXT.set((observer, trace[0]))
        request["diagnostic_request_id"] = trace[0]
        try:
            response = await handler(request)
            code = None
            # 只读取已有小型 JSON 响应中的固定错误枚举；不记录、打印或复制其他正文。
            if response.status >= 400 and isinstance(getattr(response, "body", None), bytes):
                try:
                    error_code = json.loads(response.body).get("error")
                    code = error_code if isinstance(error_code, str) and error_code in CODES else None
                except (ValueError, AttributeError, UnicodeError):
                    pass
            observer.finish(trace, response.status, code=code)
            response.headers["X-Request-Id"] = trace[0]
            return response
        except asyncio.CancelledError:
            observer.finish(trace, 499, code="response_unobserved")
            raise
        finally:
            REQUEST_CONTEXT.reset(token)
    return observe


def register_observability(app, observer):
    async def status(_request):
        return web.json_response({**observer.snapshot(), "logs": log_inventory(observer.root),
                                  "log_retention": retention_plan(observer.root,
                                      active_stream=observer.handler.baseFilename if observer.handler else None)})

    async def voice_events(request):
        # 此命名空间沿用内部 Memory Bearer/Host/回环认证；浏览器会话不能投递。
        try:
            body = await request.clone(client_max_size=2048).json()
            observer.voice_event(body)
        except (ValueError, TypeError, UnicodeError, web.HTTPRequestEntityTooLarge):
            return web.json_response({"error": "invalid_voice_event"}, status=400)
        except Exception:
            return web.json_response({"error": "voice_observation_unavailable"}, status=503)
        return web.json_response({"accepted": True}, status=202)

    async def close(_app):
        observer.close()

    app.router.add_get("/api/observability", status, allow_head=False)
    app.router.add_post("/api/internal/memory/voice-events", voice_events)
    app.on_cleanup.append(close)
