"""会话归属、限额、幂等提交。浏览器不能指定数据库、角色或模型目标。"""

import asyncio
from dataclasses import dataclass, field
import time
from uuid import uuid4, UUID

from aiohttp import web
from ..security import COOKIE, MAX_AGE

MAX_TURNS = 40
MAX_CHATS = 32
HISTORY_PAIRS = 6


@dataclass
class Chat:
    owner: str
    expires: float
    turns: list = field(default_factory=list)
    request_ids: dict = field(default_factory=dict)
    pending: bool = False


def register_chat_routes(app, backend):
    chats = {}
    tasks = set()

    def prune():
        for key, chat in list(chats.items()):
            if not chat.pending and chat.expires <= time.monotonic():
                del chats[key]

    def selected(request):
        prune()
        chat = chats.get(request.match_info["chat_id"])
        if chat is None or chat.owner != request.cookies.get(COOKIE):
            raise web.HTTPNotFound()
        return chat

    async def config(request):
        return web.json_response(backend.info() if backend else {"enabled": False})

    async def create(request):
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=403)
        prune()
        if len(chats) >= MAX_CHATS:
            return web.json_response({"error": "chat_capacity"}, status=429)
        key = str(uuid4())
        chats[key] = Chat(request.cookies[COOKIE], time.monotonic() + MAX_AGE)
        return web.json_response({"chat_id": key, "turns": [], "limit": MAX_TURNS}, status=201)

    async def get(request):
        chat = selected(request)
        return web.json_response({"chat_id": request.match_info["chat_id"],
                                  "turns": chat.turns, "pending": chat.pending, "limit": MAX_TURNS})

    async def forget(request):
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        # 仅丢弃当前临时上下文，绝不调用数据库删除接口。
        del chats[request.match_info["chat_id"]]
        return web.json_response({"forgotten": True, "long_term_memory_preserved": True})

    async def finish(chat, request_id, text, history):
        try:
            result = await asyncio.to_thread(backend.run, text, history)
            result["request_id"] = request_id
            chat.turns.append(result)
            chat.request_ids[request_id] = result
            return result
        finally:
            chat.pending = False

    async def send(request):
        chat = selected(request)
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        # 仅聊天正文放宽到 8 KiB；设备操作仍沿用应用的 1 KiB 限制。
        data_request = request.clone(client_max_size=8192)
        try:
            body = await data_request.json()
            if not isinstance(body, dict) or set(body) != {"text", "request_id"}:
                raise ValueError
            text, request_id = body["text"], body["request_id"]
            if (not isinstance(text, str) or not text.strip() or len(text) > 1000
                    or not isinstance(request_id, str) or str(UUID(request_id)) != request_id):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            return web.json_response({"error": "invalid_chat_message"}, status=400)
        previous = chat.request_ids.get(request_id)
        if previous is not None:
            if previous["input"] != text:
                return web.json_response({"error": "chat_request_conflict"}, status=409)
            return web.json_response(previous)
        if chat.pending or len(tasks) >= 2:
            return web.json_response({"error": "chat_busy"}, status=409)
        if len(chat.turns) >= MAX_TURNS:
            return web.json_response({"error": "chat_turn_limit"}, status=409)
        # 只用本会话已完成的最近六轮。失败输入仍在 L0，但不伪造对应回答。
        history = tuple({"role": role, "content": turn[key]}
                        for turn in [t for t in chat.turns if t["status"] == "completed"][-HISTORY_PAIRS:]
                        for role, key in (("user", "input"), ("assistant", "answer")))
        chat.pending = True
        task = asyncio.create_task(finish(chat, request_id, text, history))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        # 断网/关闭页面不取消已经开始的写入，更不会自动重试模型。
        return web.json_response(await asyncio.shield(task))

    async def cleanup(_app):
        if tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
        chats.clear()

    app.router.add_get("/api/chat-config", config, allow_head=False)
    app.router.add_post("/api/chats", create)
    app.router.add_get("/api/chats/{chat_id}", get, allow_head=False)
    app.router.add_post("/api/chats/{chat_id}/messages", send)
    app.router.add_delete("/api/chats/{chat_id}", forget)
    app.on_cleanup.append(cleanup)
