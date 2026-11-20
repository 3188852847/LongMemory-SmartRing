"""会话归属、限额、幂等提交。浏览器不能指定数据库、角色或模型目标。"""

import asyncio
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
import hashlib
import secrets
import re
from uuid import UUID, uuid4

from aiohttp import web
from pydantic import ValidationError
from ..chat_store import ChatStore
from ..contracts import (
    ChatMemoryFeedbackRequest,
    ChatMessageRequest,
    MemoryFeedbackReviewRequest,
)

MAX_TURNS = 40
HISTORY_PAIRS = 6
HISTORY_CHARACTERS = 24000
OWNER_COOKIE = 'longmemory_chat_owner'


@dataclass
class Chat:
    owner: str
    expires: float
    turns: list = field(default_factory=list)
    pending: bool = False
    title: str = '新聊天'
    active_request: dict | None = None

    @classmethod
    def restore(cls, payload):
        # 旧格式多存了一份按请求号索引的正文。每段最多 40 轮，直接查找即可。
        payload.pop("request_ids", None)
        chat = cls(**payload)
        if chat.pending and chat.active_request:
            chat.turns.append(interrupted_turn(chat.active_request))
        chat.pending, chat.active_request = False, None
        return chat

    def turn(self, request_id):
        return next((turn for turn in self.turns if turn.get("request_id") == request_id), None)


def interrupted_turn(active_request):
    return dict(active_request, status='interrupted', answer=None, writes=None,
                retrieved=None, memory_context=None, user_saved=False, assistant_saved=False,
                duration_ms=0, error='interrupted_write_state_unknown')


def register_chat_routes(app, backend):
    store = ChatStore(getattr(backend, "sidecar_database", backend.database)) if backend else None
    if store:
        store.open()
    # 只保留正在生成或等待落盘的会话。历史会话从旁库按需读取。
    active_chats = {}
    tasks = set()
    # 每个会话至多一份已执行、尚待旁库确认的结果。重启时仍以持久档案为准。
    unsaved_turns = {}
    saving_turns = {}

    def owner(request):
        token = request.cookies.get(OWNER_COOKIE, '')
        return hashlib.sha256(token.encode()).hexdigest() if re.fullmatch('[0-9a-f]{64}', token) else None

    def persist(key, chat):
        store.save(key, asdict(chat))

    async def save_final_turn(key, chat):
        result = unsaved_turns[key]
        finished = replace(chat, turns=[*chat.turns, result],
                           pending=False, active_request=None)
        try:
            # 线程只拿独立快照；SQLite 等锁或提交期间，其它 HTTP 请求仍可处理。
            await asyncio.to_thread(store.save, key, asdict(finished))
        except Exception:
            return False
        finally:
            del saving_turns[key]
        # 等待同一写入的查询会从这个实例读取已提交的结果。
        chat.turns = finished.turns
        chat.pending, chat.active_request = False, None
        del unsaved_turns[key]
        del active_chats[key]
        return True

    def shared_save(key, chat):
        if key not in saving_turns:
            saving_turns[key] = asyncio.create_task(save_final_turn(key, chat))
        return asyncio.shield(saving_turns[key])

    async def final_response(key, chat):
        result = unsaved_turns[key]
        if not await shared_save(key, chat):
            return web.json_response({"error": "chat_archive_unavailable"}, status=503)
        return web.json_response(result)

    def selected(request):
        key = request.match_info["chat_id"]
        chat = active_chats.get(key)
        if chat is None and store is not None:
            saved = store.get(key)
            if saved is not None:
                chat = Chat.restore(saved)
        if chat is None or chat.owner != owner(request):
            raise web.HTTPNotFound()
        return chat

    def owned_chats(owner_id):
        if store:
            for key, saved in store.owned(owner_id):
                yield key, active_chats.get(key) or Chat.restore(saved)

    async def config(request):
        return web.json_response(await asyncio.to_thread(backend.info) if backend else {"enabled": False})

    async def check_model(request):
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=403)
        # 外部调用可能等待到配置超时，因此放在线程中；请求仅由用户显式点击触发。
        return web.json_response(await asyncio.to_thread(backend.check_model))

    async def create(request):
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=403)
        key = str(uuid4())
        token = request.cookies.get(OWNER_COOKIE, '')
        if not re.fullmatch('[0-9a-f]{64}', token):
            token = secrets.token_hex(32)
        chat = Chat(hashlib.sha256(token.encode()).hexdigest(), 0)
        store.create(key, asdict(chat))
        response = web.json_response({"chat_id": key, "title": chat.title, "turns": [], "limit": MAX_TURNS}, status=201)
        response.set_cookie(OWNER_COOKIE, token, httponly=True, samesite='Strict', path='/', max_age=31536000)
        return response

    async def listing(request):
        rows = await asyncio.to_thread(store.summaries, owner(request), set(active_chats)) if store else []
        return web.json_response({'chats': rows})

    async def rename(request):
        try:
            body = await request.json()
            title = body['title']
            if set(body) != {'title'} or not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.json_response({'error': 'invalid_title'}, status=400)
        chat = selected(request)
        if chat.pending:
            return web.json_response({'error': 'chat_busy'}, status=409)
        chat.title = title.strip()
        persist(request.match_info['chat_id'], chat)
        return web.json_response({'title': chat.title})

    async def get(request):
        chat = selected(request)
        key = request.match_info["chat_id"]
        if key in unsaved_turns:
            await shared_save(key, chat)
        return web.json_response({"chat_id": key,
                                  "title": chat.title, "turns": chat.turns, "pending": chat.pending, "limit": MAX_TURNS})

    async def memory_feedback(request):
        """记录人工复核，不修改记忆、不调用模型，也不自动重跑当前回答。"""
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
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        turn = chat.turn(request_id)
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
        turn["memory_feedback"] = event
        turn["memory_feedback_events"] = [*(turn.get("memory_feedback_events") or []), event]
        persist(request.match_info["chat_id"], chat)
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
        for chat_id, chat in owned_chats(owner_id):
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
                "wrong_memory", "memory_irrelevant", "resolved", "dismissed",
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
        for chat_id, chat in owned_chats(owner_id):
            for turn in chat.turns:
                current = turn.get("memory_feedback")
                if not isinstance(current, dict) or current.get("kind") not in counts:
                    continue
                kind = current["kind"]
                counts[kind] += 1
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
                    "feedback_target_id": turn.get("request_id"),
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
                "feedback_target_id": event["feedback_event_id"],
                "feedback_message_id": event["feedback_message_id"],
                "assistant_message_id": event["assistant_message_id"],
                "kind": kind,
                "revision": 1,
                "occurred_at": event["occurred_at"],
                "retrieved_counts": layer_counts,
                "retrieval_strategy": event.get("retrieval_strategy"),
                "retrieval_evidence": event["retrieval_evidence"],
                "retrieval_evidence_recorded": bool(
                    event["retrieval_evidence_recorded"]
                ),
                "diagnostic_focus": focus,
            })
        review_targets = tuple(
            (item["source"], item["feedback_target_id"], item["revision"])
            for item in rows if item["kind"] in {"recall_miss", "wrong_memory"}
        )
        review_states = await asyncio.to_thread(
            backend.memory_feedback_review_states, review_targets,
        )
        review_counts = {"open": 0, "resolved": 0, "dismissed": 0}
        for item in rows:
            state = review_states.get(
                (item["source"], item["feedback_target_id"], item["revision"]),
                {"state": "not_applicable", "reason_code": None,
                 "review_revision": 0, "occurred_at": None},
            ) if item["kind"] in {"recall_miss", "wrong_memory"} else {
                "state": "not_applicable", "reason_code": None,
                "review_revision": 0, "occurred_at": None,
            }
            item["review"] = state
            if state["state"] in review_counts:
                review_counts[state["state"]] += 1
        if kind_filter == "issues":
            rows = [item for item in rows if item["kind"] in {"recall_miss", "wrong_memory"}
                    and item["review"]["state"] == "open"]
        elif kind_filter in {"resolved", "dismissed"}:
            rows = [item for item in rows if item["review"]["state"] == kind_filter]
        elif kind_filter != "all":
            rows = [item for item in rows if item["kind"] == kind_filter]
        rows.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
        return web.json_response({"kind": kind_filter, "counts": counts,
                                  "review_counts": review_counts,
                                  "total": len(rows), "offset": offset, "limit": limit,
                                  "items": rows[offset:offset + limit]})

    async def memory_feedback_review(request):
        """追加所有者复核结论；先核实目标仍是当前问题样本。"""

        if request.content_type != "application/json":
            return web.json_response({"error": "invalid_memory_feedback_review"}, status=400)
        try:
            payload = MemoryFeedbackReviewRequest.model_validate(await request.json())
        except (ValidationError, ValueError, TypeError):
            return web.json_response({"error": "invalid_memory_feedback_review"}, status=400)
        target_exists = False
        if payload.source == "web_chat":
            owner_id = owner(request)
            for _, chat in owned_chats(owner_id):
                turn = chat.turn(payload.target_id)
                current = turn.get("memory_feedback") if isinstance(turn, dict) else None
                if (isinstance(current, dict)
                        and current.get("kind") in {"recall_miss", "wrong_memory"}
                        and current.get("revision") == payload.feedback_revision):
                    target_exists = True
                    break
        else:
            detail = await asyncio.to_thread(
                backend.round_screen_memory_feedback_detail, payload.target_id,
            )
            target_exists = detail is not None and payload.feedback_revision == 1
        if not target_exists:
            return web.json_response({"error": "memory_feedback_review_target_stale"}, status=409)
        try:
            result = await asyncio.to_thread(
                backend.record_memory_feedback_review,
                source=payload.source, target_id=payload.target_id,
                feedback_revision=payload.feedback_revision, action=payload.action,
                reason_code=payload.reason_code,
                expected_review_revision=payload.expected_review_revision,
            )
        except ValueError as exc:
            code = str(exc)
            status = 409 if code in {
                "memory_feedback_review_conflict",
                "memory_feedback_review_transition_invalid",
            } else 400
            return web.json_response({"error": code}, status=status)
        return web.json_response(result)

    async def forget(request):
        chat = selected(request)
        if chat.pending:
            return web.json_response({"error": "chat_busy"}, status=409)
        # 兼容原删除接口：只删除网页会话档案，不删除 L0/L1；页面不默认调用。
        store.remove(request.match_info['chat_id'])
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
            metadata = {"session_id": "web:" + key} if getattr(backend, "_runtime", None) is not None and not backend.memory_runtime().legacy_sqlite else {}
            result = await asyncio.to_thread(backend.run, text, history, **metadata)
            result["request_id"] = request_id
        except Exception:
            # 后端未交回终态，沿用崩溃恢复的结果，保留请求号和写入状态的不确定性。
            result = interrupted_turn(chat.active_request)
        unsaved_turns[key] = result
        return await final_response(key, chat)

    async def send(request):
        key = request.match_info["chat_id"]
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
        chat = selected(request)
        previous = chat.turn(request_id)
        if previous is not None:
            if previous["input"] != text:
                return web.json_response({"error": "chat_request_conflict"}, status=409)
            return web.json_response(previous)
        if chat.active_request and chat.active_request["request_id"] == request_id:
            if chat.active_request["input"] != text:
                return web.json_response({"error": "chat_request_conflict"}, status=409)
            if key in unsaved_turns:
                return await final_response(key, chat)
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
        persist(key, chat)
        active_chats[key] = chat
        task = asyncio.create_task(finish(key, chat, request_id, text, history))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        # 断网/关闭页面不取消已经开始的写入，更不会自动重试模型。
        return await asyncio.shield(task)

    async def cleanup(_app):
        if tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
        if saving_turns:
            await asyncio.gather(*tuple(saving_turns.values()), return_exceptions=True)
        # 退出前给仍在内存中的终态最后一次提交机会。个别旁库失败沿用中断恢复。
        await asyncio.gather(*(shared_save(key, active_chats[key]) for key in tuple(unsaved_turns)),
                             return_exceptions=True)
        unsaved_turns.clear()
        active_chats.clear()
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
    app.router.add_post("/api/chat-memory-feedback/reviews", memory_feedback_review)
    app.router.add_get(
        "/api/round-screen-memory-feedback/{event_id}",
        round_screen_feedback_detail, allow_head=False,
    )
    app.router.add_delete("/api/chats/{chat_id}", forget)
    app.on_cleanup.append(cleanup)
    return lambda: not tasks and not active_chats
