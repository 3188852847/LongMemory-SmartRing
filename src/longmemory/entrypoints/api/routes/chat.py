"""会话归属、限额、幂等提交。浏览器不能指定数据库、角色或模型目标。"""

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
import hashlib
import secrets
import re
from uuid import UUID, uuid4

from aiohttp import web
from pydantic import ValidationError
from ..chat_store import ChatStore
from ..contracts import ChatMemoryFeedbackRequest, ChatMessageRequest

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
        # JSON 会把 turns 与 request_ids 中的同一轮反序列化为两个 dict。
        # 重新绑定到 turns 的对象，确保重启后的反馈、读取和幂等回放看到同一版本。
        for turn in chat.turns:
            if isinstance(turn.get('request_id'), str):
                chat.request_ids[turn['request_id']] = turn
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

    async def check_model(request):
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=403)
        # 外部调用可能等待到配置超时，因此放在线程中；请求仅由用户显式点击触发。
        return web.json_response(await asyncio.to_thread(backend.check_model))

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

    async def memory_feedback(request):
        """记录人工复核，不修改记忆、不调用模型，也不自动重跑当前回答。"""
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        try:
            request_id = request.match_info["request_id"]
            # 路径也坚持 canonical UUID，避免旁库中出现同一 ID 的不同文本形式。
            if str(UUID(request_id)) != request_id:
                raise ValueError
            if request.content_type != "application/json":
                raise ValueError
            body = ChatMemoryFeedbackRequest.model_validate(await request.json())
        except (ValidationError, ValueError, TypeError, UnicodeError):
            return web.json_response({"error": "invalid_memory_feedback"}, status=400)
        turn = chat.request_ids.get(request_id)
        if turn is None or turn.get("status") != "completed" or not turn.get("answer"):
            return web.json_response({"error": "feedback_turn_unavailable"}, status=404)
        current = turn.get("memory_feedback")
        revision = current.get("revision", 0) if isinstance(current, dict) else 0
        if body.expected_revision != revision:
            return web.json_response({"error": "memory_feedback_conflict", "current": current}, status=409)
        if revision >= 32:
            return web.json_response({"error": "memory_feedback_revision_limit"}, status=409)
        event = {"kind": body.kind, "revision": revision + 1,
                 "occurred_at": datetime.now(UTC).isoformat()}
        old_current = current
        old_events = list(turn.get("memory_feedback_events") or [])
        turn["memory_feedback"] = event
        turn["memory_feedback_events"] = old_events + [event]
        try:
            persist(request.match_info["chat_id"], chat)
        except Exception:
            if old_current is None:
                turn.pop("memory_feedback", None)
            else:
                turn["memory_feedback"] = old_current
            turn["memory_feedback_events"] = old_events
            raise
        return web.json_response({"feedback": event})

    async def memory_feedback_daily(request):
        """按自然日聚合复核动作；只返回定位信息，不复制私人对话正文。"""
        try:
            if set(request.query) != {"local_date", "utc_offset_minutes"}:
                raise ValueError
            local_date = date.fromisoformat(request.query["local_date"])
            offset_minutes = int(request.query["utc_offset_minutes"])
            if not -720 <= offset_minutes <= 840:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "invalid_feedback_daily_query"}, status=400)
        owner_id = owner(request)
        counts = {kind: 0 for kind in (
            "memory_ok", "recall_miss", "wrong_memory", "memory_irrelevant"
        )}
        current_counts = dict.fromkeys(counts, 0)
        rows = []
        current_rows = []
        offset = timedelta(minutes=offset_minutes)
        for chat_id, chat in chats.items():
            if chat.owner != owner_id:
                continue
            for turn in chat.turns:
                current = turn.get("memory_feedback")
                if isinstance(current, dict):
                    try:
                        current_time = datetime.fromisoformat(current["occurred_at"])
                        current_kind = current["kind"]
                        if (current_time.tzinfo is not None
                                and (current_time + offset).date() == local_date
                                and current_kind in current_counts):
                            current_counts[current_kind] += 1
                            current_rows.append({
                                "chat_id": chat_id, "chat_title": chat.title,
                                "request_id": turn.get("request_id"),
                                "kind": current_kind,
                                "revision": current.get("revision"),
                                "occurred_at": current["occurred_at"],
                            })
                    except (KeyError, TypeError, ValueError):
                        pass
                for event in turn.get("memory_feedback_events") or []:
                    try:
                        occurred = datetime.fromisoformat(event["occurred_at"])
                        if occurred.tzinfo is None or (occurred + offset).date() != local_date:
                            continue
                        kind = event["kind"]
                        if kind not in counts:
                            continue
                    except (KeyError, TypeError, ValueError):
                        continue
                    counts[kind] += 1
                    rows.append({
                        "chat_id": chat_id, "chat_title": chat.title,
                        "request_id": turn.get("request_id"), "kind": kind,
                        "revision": event.get("revision"),
                        "occurred_at": event["occurred_at"],
                        "is_current": isinstance(current, dict)
                            and current.get("revision") == event.get("revision"),
                    })
        rows.sort(key=lambda item: item["occurred_at"], reverse=True)
        current_rows.sort(key=lambda item: item["occurred_at"], reverse=True)
        return web.json_response({"local_date": local_date.isoformat(),
                                  "utc_offset_minutes": offset_minutes,
                                  "action_counts": counts, "total": len(rows),
                                  "items": rows[:100], "limited": len(rows) > 100,
                                  "current_counts": current_counts,
                                  "current_total": len(current_rows),
                                  "current_items": current_rows[:100],
                                  "current_limited": len(current_rows) > 100})

    async def memory_feedback_index(request):
        """跨日期读取每轮当前判断；只提供诊断定位元数据，不复制正文。"""
        try:
            if set(request.query) != {"kind", "offset", "limit"}:
                raise ValueError
            kind_filter = request.query["kind"]
            if kind_filter not in {
                "issues", "all", "memory_ok", "recall_miss",
                "wrong_memory", "memory_irrelevant",
            }:
                raise ValueError
            offset = int(request.query["offset"])
            limit = int(request.query["limit"])
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "invalid_feedback_index_query"}, status=400)
        owner_id = owner(request)
        counts = {kind: 0 for kind in (
            "memory_ok", "recall_miss", "wrong_memory", "memory_irrelevant"
        )}
        rows = []
        for chat_id, chat in chats.items():
            if chat.owner != owner_id:
                continue
            for turn in chat.turns:
                current = turn.get("memory_feedback")
                if not isinstance(current, dict) or current.get("kind") not in counts:
                    continue
                kind = current["kind"]
                counts[kind] += 1
                if (kind_filter == "issues" and kind not in {"recall_miss", "wrong_memory"}) \
                        or (kind_filter not in {"issues", "all"} and kind != kind_filter):
                    continue
                layer_counts = {
                    "l1": len(turn.get("retrieved") or []),
                    "l2": len(turn.get("scenario_retrieved") or []),
                    "l3": len(turn.get("persona_retrieved") or []),
                }
                recalled = sum(layer_counts.values())
                focus = {
                    "memory_ok": "normal_control",
                    "memory_irrelevant": "negative_control",
                    "recall_miss": "context_or_answer_use" if recalled else "retrieval",
                    "wrong_memory": (
                        "memory_content_freshness_subject_or_ranking"
                        if recalled else "short_term_or_answer_model"
                    ),
                }[kind]
                rows.append({
                    "source": "web_chat",
                    "chat_id": chat_id, "chat_title": chat.title,
                    "request_id": turn.get("request_id"), "kind": kind,
                    "revision": current.get("revision"),
                    "occurred_at": current.get("occurred_at"),
                    "retrieved_counts": layer_counts,
                    "diagnostic_focus": focus,
                })
        # 圆屏自然反馈与网页人工标记共享诊断口径，但来源和定位方式必须
        # 明确区分；这里不读取、复制或返回任何语音对话正文。
        for event in await asyncio.to_thread(backend.round_screen_memory_feedback):
            kind = event["event_kind"]
            counts[kind] += 1
            if (kind_filter == "issues" and kind not in {"recall_miss", "wrong_memory"}) \
                    or (kind_filter not in {"issues", "all"} and kind != kind_filter):
                continue
            layer_counts = {
                "l1": event["retrieved_l1_count"],
                "l2": event["retrieved_l2_count"],
                "l3": event["retrieved_l3_count"],
            }
            recalled = sum(layer_counts.values())
            focus = (
                "context_or_answer_use" if kind == "recall_miss" and recalled
                else "retrieval" if kind == "recall_miss"
                else "memory_content_freshness_subject_or_ranking" if recalled
                else "short_term_or_answer_model"
            )
            rows.append({
                "source": "round_screen",
                "chat_id": None,
                "chat_title": "圆屏语音",
                "request_id": event["target_user_message_id"],
                "feedback_event_id": event["feedback_event_id"],
                "feedback_message_id": event["feedback_message_id"],
                "assistant_message_id": event["assistant_message_id"],
                "kind": kind,
                "revision": 1,
                "occurred_at": event["occurred_at"],
                "retrieved_counts": layer_counts,
                "retrieval_evidence": event["retrieval_evidence"],
                "retrieval_evidence_recorded": bool(
                    event["retrieval_evidence_recorded"]
                ),
                "diagnostic_focus": focus,
            })
        rows.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
        return web.json_response({"kind": kind_filter, "counts": counts,
                                  "total": len(rows), "offset": offset, "limit": limit,
                                  "items": rows[offset:offset + limit]})

    async def forget(request):
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        # 兼容原删除接口：只删除网页会话档案，不删除 L0/L1；页面不默认调用。
        store.remove(request.match_info['chat_id'])
        del chats[request.match_info["chat_id"]]
        return web.json_response({"forgotten": True, "long_term_memory_preserved": True})

    async def round_screen_feedback_detail(request):
        try:
            event_id = request.match_info["event_id"]
            if str(UUID(event_id)) != event_id:
                raise ValueError
        except (ValueError, TypeError):
            return web.json_response({"error": "invalid_feedback_event_id"}, status=400)
        item = await asyncio.to_thread(
            backend.round_screen_memory_feedback_detail, event_id,
        )
        if item is None:
            return web.json_response({"error": "feedback_event_not_found"}, status=404)
        return web.json_response(item)

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
    app.router.add_post("/api/chat-model/check", check_model)
    app.router.add_post("/api/chats", create)
    app.router.add_get('/api/chats', listing, allow_head=False)
    app.router.add_post('/api/chats/{chat_id}/title', rename)
    app.router.add_get("/api/chats/{chat_id}", get, allow_head=False)
    app.router.add_post("/api/chats/{chat_id}/messages", send)
    app.router.add_post("/api/chats/{chat_id}/turns/{request_id}/memory-feedback", memory_feedback)
    app.router.add_get("/api/chat-memory-feedback/daily", memory_feedback_daily, allow_head=False)
    app.router.add_get("/api/chat-memory-feedback", memory_feedback_index, allow_head=False)
    app.router.add_get(
        "/api/round-screen-memory-feedback/{event_id}",
        round_screen_feedback_detail, allow_head=False,
    )
    app.router.add_delete("/api/chats/{chat_id}", forget)
    app.on_cleanup.append(cleanup)
