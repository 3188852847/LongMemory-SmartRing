"""只供同机小智进程使用的记忆 Runtime 接口。"""

import asyncio
from dataclasses import asdict
import re
from uuid import UUID
from time import perf_counter

from aiohttp import web

from longmemory.entrypoints.xiaozhi.mapping import extract_user_text
from longmemory.entrypoints.api.observability import bind_voice_request
from longmemory.application.round_screen_turns import memory_receipt
from longmemory.methods.hy_memory.observation import DETAIL_VERSION, Observation, span, response_headers


_MAX_ANSWER_CHARS = 16_000
# 小智默认以一对 JSON 代理项编码非 BMP 字符，每字符最多 12 字节。
# prepare 默认使用 ASCII JSON，小智最多读取 64 KiB，两版协议仅回传其中的证据。
# 使用同样的 JSON 编码回传，或直接发送 UTF-8，均在此预算内；另留 1 KiB 给固定字段。
_COMPLETION_BODY_BYTES = _MAX_ANSWER_CHARS * 12 + 64 * 1024 + 1024


def register_memory_runtime_routes(app, backend):
    if backend is None:
        return

    async def status(_request):
        result = await asyncio.to_thread(backend.memory_runtime().status)
        return web.json_response({"version": 1, **result})

    async def prepare(request):
        bind_voice_request(request)
        request = request.clone(client_max_size=32768)
        try:
            body = await request.json()
            if (not isinstance(body, dict) or set(body) != {"version", "query", "client_round_id", "session_id"}
                    or body.get("version") != 1):
                raise ValueError
            text = extract_user_text(body.get("query"))
            for name in ("client_round_id", "session_id"):
                if not isinstance(body[name], str) or re.fullmatch(r"[0-9a-f]{24,32}", body[name]) is None:
                    raise ValueError
            metadata = {key: body[key] for key in ("client_round_id", "session_id")}
            metadata["request_id"] = request.get("diagnostic_request_id")
            voice_round_id = request.headers.get("X-Voice-Round-Id", "")
            metadata["voice_round_id"] = voice_round_id if re.fullmatch(r"[0-9a-f]{24}", voice_round_id) else None
        except (ValueError, TypeError, UnicodeError):
            return web.json_response({"error": "invalid_memory_request", "version": 1}, status=400)
        detailed=request.headers.get('X-Memory-Observe-Detail')==DETAIL_VERSION
        observation = (Observation(body['client_round_id'],detail=detailed) if request.headers.get('X-Memory-Observe')=='1'
                       else None)
        try:
            if observation is None:
                prepared, _ = await asyncio.to_thread(backend.prepare_round_screen_user, text, **metadata)
            else:
                queued=perf_counter()
                def prepare_observed():
                    observation.add('api_queue_ms',max(0,perf_counter()-queued)*1000)
                    with span('api_prepare_ms'):
                        result=backend.prepare_round_screen_user(text,
                            timing_callback=observation.runtime_event,**metadata)
                        for name,value in asdict(result[0].timings).items():
                            observation.add('prepare_'+name,value)
                        return result
                with observation.activate():
                    prepared, _ = await asyncio.to_thread(prepare_observed)
        except ValueError:
            headers=response_headers(observation)
            return web.json_response({"error": "round_screen_prepare_conflict", "version": 1}, status=409,headers=headers)
        response = {
            "version": 1,
            "context": prepared.support.context,
            "turn_id": prepared.event.event_id,
            "added": (sum(item.operation == "add" for item in prepared.observation.writes)
                      if prepared.observation.writes is not None else None),
            "retrieved": (len(prepared.support.retrieved)
                          if prepared.support.retrieved is not None else None),
            "memory_processing": prepared.observation.processing_status,
            "memory_warning": prepared.observation.warning_code,
            "retrieval_strategy": prepared.support.retrieval_strategy,
            "retrieval_warning": prepared.support.warning_code,
            "memory_write_enabled": prepared.write_enabled,
            "memory_use_enabled": prepared.use_enabled,
            # 只暴露各阶段耗时，便于定位圆屏首句延迟；不包含正文或模型响应。
            "timings_ms": asdict(prepared.timings),
            "memory_command": (asdict(prepared.memory_command)
                               if prepared.memory_command is not None else None),
            "follow_up_suggestion": None,
            "temporary_interaction": (
                asdict(prepared.temporary_interaction)
                if prepared.temporary_interaction is not None else None
            ),
            "round_screen_feedback": None,
            # 小智当前 Memory 插槽不能直接短路回答；把应用层固定回执作为
            # 独立字段交给薄适配器，以便和普通记忆证据使用不同提示契约。
            "command_reply": prepared.memory_command.notice if prepared.memory_command else None,
        }
        response.update(memory_protocol=2, memory_receipt=memory_receipt(prepared))
        response["external_model_pause"] = prepared.observation.warning_code == "external_model_budget_paused"
        headers=response_headers(observation)
        return web.json_response(response,headers=headers)

    async def voice_model_configuration(_request):
        try:
            result = await asyncio.to_thread(backend.memory_runtime().voice_model_configuration)
        except ValueError:
            return web.json_response({"error": "owned_model_service_unavailable"}, status=503)
        return web.json_response(result)

    async def complete(request):
        """接收同机小智的最终助手文本；不代表音频已在设备播放完成。"""

        bind_voice_request(request)
        request = request.clone(client_max_size=_COMPLETION_BODY_BYTES)
        try:
            body = await request.json()
            required_v2 = {"version", "memory_protocol", "turn_id", "answer", "memory_receipt", "client_round_id"}
            if (not isinstance(body, dict) or set(body) != required_v2 or body["version"] != 1 or body["memory_protocol"] != 2
                    or not isinstance(body["answer"], str) or not body["answer"].strip()
                    or len(body["answer"]) > _MAX_ANSWER_CHARS or not isinstance(body["turn_id"], str)
                    or str(UUID(body["turn_id"])) != body["turn_id"]
                    or not isinstance(body["client_round_id"], str)
                    or re.fullmatch(r"[0-9a-f]{24,32}", body["client_round_id"]) is None
                    or not isinstance(body["memory_receipt"], dict)):
                raise ValueError
            try:
                result = await asyncio.to_thread(backend.complete_round_screen_turn,
                    turn_id=body["turn_id"], answer=body["answer"], retrieved_counts=None,
                    receipt=body["memory_receipt"], client_round_id=body["client_round_id"],
                    request_id=request.get("diagnostic_request_id"))
            except ValueError as error:
                return web.json_response({"version": 1, "error": str(error)}, status=409)
            return web.json_response({"version": 1, "assistant_event_id": result.assistant_message_id,
                "created": result.created, "playback_acknowledgement": "unavailable"})
        except (ValueError, TypeError, KeyError, UnicodeError):
            return web.json_response(
                {"error": "invalid_memory_completion", "version": 1}, status=400,
            )
    async def cancel(request):
        bind_voice_request(request)
        try:
            body = await request.clone(client_max_size=2048).json()
            if (not isinstance(body, dict) or set(body) != {"version", "turn_id", "reason", "client_round_id"}
                    or body["version"] != 1 or not isinstance(body["turn_id"], str)
                    or str(UUID(body["turn_id"])) != body["turn_id"]
                    or not isinstance(body["client_round_id"], str)
                    or re.fullmatch(r"[0-9a-f]{24,32}", body["client_round_id"]) is None):
                raise ValueError
            runtime = backend.memory_runtime()
            state = await asyncio.to_thread(runtime.cancel_round_screen, body["turn_id"],
                reason=body["reason"], client_round_id=body["client_round_id"],
                request_id=request.get("diagnostic_request_id"))
            return web.json_response({"version": 1, "state": state["state"]})
        except (ValueError, TypeError, KeyError, UnicodeError):
            return web.json_response({"error": "round_screen_cancel_invalid"}, status=409)

    app.router.add_get("/api/internal/memory/status", status, allow_head=False)
    app.router.add_post("/api/internal/memory/prepare", prepare)
    app.router.add_post("/api/internal/memory/complete", complete)
    app.router.add_post("/api/internal/memory/cancel", cancel)
    app.router.add_get("/api/internal/memory/model-configuration", voice_model_configuration, allow_head=False)
