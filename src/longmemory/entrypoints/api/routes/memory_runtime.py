"""只供同机小智进程使用的记忆 Runtime 接口。"""

import asyncio
from dataclasses import asdict
from hashlib import sha256
import sqlite3
from uuid import UUID

from aiohttp import web

from longmemory.entrypoints.xiaozhi.mapping import extract_user_text


def _retrieval_evidence(prepared):
    """生成不含正文的召回索引；指纹用于发现条目后来是否发生变化。"""

    rows = []
    groups = (
        ("l1", prepared.support.retrieved or (), lambda item: item.item_id,
         lambda item: item.content),
        ("l2", prepared.scenarios, lambda item: item.scenario_id,
         lambda item: item.title + "\n" + item.summary),
        ("l3", prepared.personas, lambda item: item.persona_id,
         lambda item: item.label + "\n" + item.statement),
    )
    for layer, items, identify, content in groups:
        for rank, item in enumerate(items, 1):
            rows.append({
                "layer": layer,
                "item_id": identify(item),
                "rank": rank,
                "content_sha256": sha256(content(item).encode("utf-8")).hexdigest(),
            })
    return rows


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
        prepared, feedback = await asyncio.to_thread(
            backend.prepare_round_screen_user, text,
        )
        feedback_notice = None
        if feedback is not None and feedback.recorded:
            feedback_notice = {
                "recall_miss": (
                    "已记录你对上一轮回答的反馈：它可能没有召回相关记忆。"
                    "这条记录只用于后续复核，尚未自动修改长期记忆。"
                ),
                "wrong_memory": (
                    "已记录你对上一轮回答的反馈：它可能使用了错误记忆。"
                    "这条记录只用于后续复核，尚未自动修改长期记忆。"
                ),
            }[feedback.kind]
        follow_up_notice = None
        if (
            prepared.follow_up_suggestion is not None
            and prepared.follow_up_suggestion.status == "candidate_created"
        ):
            follow_up_notice = (
                "已经按你说的时间形成一条跟进候选，但目前还没有启用主动联系。"
                "请稍后在控制台的主动交流设置中核对并启用。"
            )
        command_reply = (
            prepared.memory_command.notice
            if prepared.memory_command is not None
            else feedback_notice or follow_up_notice
        )
        return web.json_response({
            "version": 1,
            "context": prepared.support.context,
            "turn_id": prepared.event.event_id,
            "added": sum(item.operation == "add" for item in prepared.observation.writes),
            "retrieved": len(prepared.support.retrieved or ()),
            "retrieval_evidence": _retrieval_evidence(prepared),
            "memory_processing": prepared.observation.processing_status,
            "memory_warning": prepared.observation.warning_code,
            "retrieval_strategy": prepared.support.retrieval_strategy,
            "retrieval_warning": prepared.support.warning_code,
            "memory_write_enabled": prepared.write_enabled,
            "memory_use_enabled": prepared.use_enabled,
            "scenario_use_enabled": prepared.scenario_use_enabled,
            "scenario_retrieved": [asdict(item) for item in prepared.scenarios],
            "persona_use_enabled": prepared.persona_use_enabled,
            "persona_retrieved": [asdict(item) for item in prepared.personas],
            # 只暴露各阶段耗时，便于定位圆屏首句延迟；不包含正文或模型响应。
            "timings_ms": asdict(prepared.timings),
            "memory_command": (asdict(prepared.memory_command)
                               if prepared.memory_command is not None else None),
            "follow_up_suggestion": (
                asdict(prepared.follow_up_suggestion)
                if prepared.follow_up_suggestion is not None else None
            ),
            "round_screen_feedback": (
                asdict(feedback) if feedback is not None else None
            ),
            # 小智当前 Memory 插槽不能直接短路回答；把应用层固定回执作为
            # 独立字段交给薄适配器，以便和普通记忆证据使用不同提示契约。
            "command_reply": command_reply,
        })

    async def complete(request):
        """接收同机小智的最终助手文本；不代表音频已在设备播放完成。"""

        request = request.clone(client_max_size=32768)
        try:
            body = await request.json()
            required = {"version", "turn_id", "answer", "retrieved_counts"}
            allowed_shapes = (required, required | {"retrieval_evidence"})
            if (not isinstance(body, dict) or set(body) not in allowed_shapes
                    or body.get("version") != 1):
                raise ValueError
            turn_id = body["turn_id"]
            answer = body["answer"]
            counts = body["retrieved_counts"]
            evidence = body.get("retrieval_evidence")
            if (not isinstance(turn_id, str) or str(UUID(turn_id)) != turn_id
                    or not isinstance(answer, str) or not answer.strip()
                    or len(answer) > 16000 or not isinstance(counts, dict)
                    or set(counts) != {"l1", "l2", "l3"}
                    or any(type(value) is not int or not 0 <= value <= 100
                           for value in counts.values())):
                raise ValueError
            if evidence is not None and not isinstance(evidence, list):
                raise ValueError
        except (ValueError, TypeError, KeyError, UnicodeError):
            return web.json_response(
                {"error": "invalid_memory_completion", "version": 1}, status=400,
            )
        try:
            result = await asyncio.to_thread(
                backend.complete_round_screen_turn,
                turn_id=turn_id, answer=answer, retrieved_counts=counts,
                retrieval_evidence=(tuple(evidence) if evidence is not None else None),
            )
        except ValueError as error:
            code = str(error)
            status = 404 if code == "round_screen_user_turn_not_found" else 409
            return web.json_response({"error": code, "version": 1}, status=status)
        except sqlite3.Error:
            return web.json_response(
                {"error": "memory_completion_unavailable", "version": 1}, status=503,
            )
        return web.json_response({
            "version": 1,
            "assistant_event_id": result.assistant_message_id,
            "created": result.created,
            "playback_acknowledgement": "unavailable",
        })

    app.router.add_get("/api/internal/memory/status", status, allow_head=False)
    app.router.add_post("/api/internal/memory/prepare", prepare)
    app.router.add_post("/api/internal/memory/complete", complete)
