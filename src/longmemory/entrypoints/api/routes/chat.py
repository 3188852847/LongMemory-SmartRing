"""会话归属、限额、幂等提交。浏览器不能指定数据库、角色或模型目标。"""

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
import secrets
import re
from uuid import uuid4

from aiohttp import web
from pydantic import ValidationError
from ..chat_store import ChatStore
from ..contracts import ChatMessageRequest

MAX_TURNS = 40
MAX_CHATS = 32
HISTORY_PAIRS = 6
HISTORY_CHARACTERS = 24000
OWNER_COOKIE = 'longmemory_chat_owner'


@dataclass
class Chat:
    owner: str
    expires: float
    turns: list = field(default_factory=list)
    request_ids: dict = field(default_factory=dict)
    pending: bool = False
    title: str = '新聊天'
    active_request: dict | None = None


def register_chat_routes(app, backend):
    store = ChatStore(backend.database) if backend else None
    chats = {key: Chat(**value) for key, value in store.load().items()} if store else {}
    # 崩溃中断不是模型失败或“未写入”：保留请求号，禁止自动重复执行。
    for chat in chats.values():
        if chat.pending and chat.active_request:
            result = dict(chat.active_request, status='interrupted', answer=None, writes=None,
                          retrieved=None, memory_context=None, user_saved=False, assistant_saved=False,
                          duration_ms=0, error='interrupted_write_state_unknown')
            chat.turns.append(result)
            chat.request_ids[result['request_id']] = result
        chat.pending = False
        chat.active_request = None
    tasks = set()

    def owner(request):
        token = request.cookies.get(OWNER_COOKIE, '')
        return hashlib.sha256(token.encode()).hexdigest() if re.fullmatch('[0-9a-f]{64}', token) else None

    def persist(key, chat):
        store.save(key, asdict(chat))

    def prune():
        pass  # 持久会话不按短期认证 cookie 的寿命删除。

    def selected(request):
        prune()
        chat = chats.get(request.match_info["chat_id"])
        if chat is None or chat.owner != owner(request):
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
        token = request.cookies.get(OWNER_COOKIE, '')
        if not re.fullmatch('[0-9a-f]{64}', token):
            token = secrets.token_hex(32)
        chat = Chat(hashlib.sha256(token.encode()).hexdigest(), 0)
        persist(key, chat)
        chats[key] = chat
        response = web.json_response({"chat_id": key, "title": chat.title, "turns": [], "limit": MAX_TURNS}, status=201)
        response.set_cookie(OWNER_COOKIE, token, httponly=True, samesite='Strict', path='/', max_age=31536000)
        return response

    async def listing(request):
        return web.json_response({'chats': [{'chat_id': key, 'title': chat.title, 'turn_count': len(chat.turns)}
                                           for key, chat in reversed(list(chats.items())) if chat.owner == owner(request)]})

    async def rename(request):
        chat = selected(request)
        if chat.pending:
            return web.json_response({'error': 'chat_busy'}, status=409)
        try:
            body = await request.json()
            title = body['title']
            if set(body) != {'title'} or not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.json_response({'error': 'invalid_title'}, status=400)
        old = chat.title
        chat.title = title.strip()
        try:
            persist(request.match_info['chat_id'], chat)
        except Exception:
            chat.title = old
            raise
        return web.json_response({'title': chat.title})

    async def get(request):
        chat = selected(request)
        return web.json_response({"chat_id": request.match_info["chat_id"],
                                  "title": chat.title, "turns": chat.turns, "pending": chat.pending, "limit": MAX_TURNS})

    async def forget(request):
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        # 兼容原删除接口：只删除网页会话档案，不删除 L0/L1；页面不默认调用。
        store.remove(request.match_info['chat_id'])
        del chats[request.match_info["chat_id"]]
        return web.json_response({"forgotten": True, "long_term_memory_preserved": True})

    async def finish(key, chat, request_id, text, history):
        try:
            result = await asyncio.to_thread(backend.run, text, history)
            result["request_id"] = request_id
            chat.turns.append(result)
            chat.request_ids[request_id] = result
            chat.pending = False
            chat.active_request = None
            persist(key, chat)
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
            message = ChatMessageRequest.model_validate(body)
            text, request_id = message.text, message.request_id
        except (ValidationError, ValueError, TypeError, UnicodeError):
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
        recent, used = [], 0
        for turn in reversed([t for t in chat.turns if t['status'] == 'completed'][-HISTORY_PAIRS:]):
            size = len(turn['input']) + len(turn['answer'])
            if used + size > HISTORY_CHARACTERS:
                break
            recent.append(turn)
            used += size
        history = tuple({"role": role, "content": turn[key]}
                        for turn in reversed(recent)
                        for role, key in (("user", "input"), ("assistant", "answer")))
        chat.pending = True
        chat.active_request = {'request_id': request_id, 'input': text}
        try:
            persist(request.match_info['chat_id'], chat)
        except Exception:
            chat.pending = False
            chat.active_request = None
            raise
        task = asyncio.create_task(finish(request.match_info['chat_id'], chat, request_id, text, history))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        # 断网/关闭页面不取消已经开始的写入，更不会自动重试模型。
        return web.json_response(await asyncio.shield(task))

    async def cleanup(_app):
        if tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
        chats.clear()
        if store:
            store.close()

    app.router.add_get("/api/chat-config", config, allow_head=False)
    app.router.add_post("/api/chats", create)
    app.router.add_get('/api/chats', listing, allow_head=False)
    app.router.add_post('/api/chats/{chat_id}/title', rename)
    app.router.add_get("/api/chats/{chat_id}", get, allow_head=False)
    app.router.add_post("/api/chats/{chat_id}/messages", send)
    app.router.add_delete("/api/chats/{chat_id}", forget)
    app.on_cleanup.append(cleanup)
