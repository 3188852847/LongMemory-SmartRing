"""本机控制台主动联系设置；保存设置本身不会创建或投递消息。"""

import asyncio

from aiohttp import web
from pydantic import ValidationError

from ..contracts import (
    CompanionStrategyDismissRequest,
    ProactivePlaybackConfirmationRequest,
    ProactivePolicyRequest,
    ProactiveScheduleOverrideArmRequest,
    ProactiveScheduleOverrideCancelRequest,
    ProactiveTestRequest,
    ProactiveTopicDisableRequest,
    ProactiveTopicSeedRequest,
)
from ..memory_backend import MemoryAccessError


def register_proactive_policy_routes(app, backend, client, operation_lock):
    async def policy(request):
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(backend.proactive_policy)
            else:
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                try:
                    body = ProactivePolicyRequest.model_validate(await request.json())
                except (ValidationError, ValueError, UnicodeError):
                    raise web.HTTPBadRequest() from None
                result = await asyncio.to_thread(backend.update_proactive_policy, body)
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/proactive-policy", policy, allow_head=False)
    app.router.add_put("/api/proactive-policy", policy)

    async def schedule_status(_request):
        try:
            result = await asyncio.to_thread(backend.proactive_schedule_status)
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get(
        "/api/proactive-schedule-status", schedule_status, allow_head=False,
    )

    async def arm_schedule_override(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ProactiveScheduleOverrideArmRequest.model_validate(
                await request.json()
            )
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        try:
            result = await asyncio.to_thread(
                backend.arm_proactive_schedule_override, body,
            )
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    async def cancel_schedule_override(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ProactiveScheduleOverrideCancelRequest.model_validate(
                await request.json()
            )
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        try:
            result = await asyncio.to_thread(
                backend.cancel_proactive_schedule_override,
                request.match_info["override_id"],
                expected_revision=body.expected_revision,
            )
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_post(
        "/api/proactive-schedule-override/arm", arm_schedule_override,
    )
    app.router.add_post(
        r"/api/proactive-schedule-override/{override_id:[0-9a-f]{32}}/cancel",
        cancel_schedule_override,
    )

    async def test_once(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ProactiveTestRequest.model_validate(await request.json())
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        async with operation_lock:
            try:
                result = await backend.proactive_test(body, client)
                return web.json_response(result)
            except MemoryAccessError as error:
                return web.json_response({"error": error.code}, status=error.status)

    app.router.add_post("/api/proactive-outreach/test", test_once)

    async def history(request):
        raw_limit = request.query.get("limit", "20")
        try:
            limit = int(raw_limit)
            if str(limit) != raw_limit:
                raise ValueError
            result = await asyncio.to_thread(backend.proactive_history, limit=limit)
            return web.json_response(result)
        except ValueError:
            raise web.HTTPBadRequest() from None
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/proactive-outreach", history, allow_head=False)

    async def topic_seeds(request):
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(backend.list_proactive_topic_seeds)
            else:
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                try:
                    body = ProactiveTopicSeedRequest.model_validate(await request.json())
                except (ValidationError, ValueError, UnicodeError):
                    raise web.HTTPBadRequest() from None
                result = await asyncio.to_thread(backend.create_proactive_topic_seed, body)
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/proactive-topic-seeds", topic_seeds, allow_head=False)
    app.router.add_post("/api/proactive-topic-seeds", topic_seeds)

    async def disable_topic_seed(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ProactiveTopicDisableRequest.model_validate(await request.json())
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        try:
            result = await asyncio.to_thread(
                backend.disable_proactive_topic_seed,
                request.match_info["seed_id"],
                expected_revision=body.expected_revision,
            )
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_post(
        r"/api/proactive-topic-seeds/{seed_id:[0-9a-f]{32}}/disable",
        disable_topic_seed,
    )

    async def confirm_played(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = ProactivePlaybackConfirmationRequest.model_validate(
                await request.json()
            )
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        async with operation_lock:
            try:
                result = await asyncio.to_thread(
                    backend.confirm_proactive_played,
                    request.match_info["outreach_id"],
                    expected_revision=body.expected_revision,
                )
                return web.json_response(result)
            except MemoryAccessError as error:
                return web.json_response({"error": error.code}, status=error.status)

    app.router.add_post(
        r"/api/proactive-outreach/{outreach_id:[0-9a-f]{32}}/confirm-played",
        confirm_played,
    )

    async def strategy_candidates(request):
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(
                    backend.list_companion_strategy_candidates,
                )
            else:
                # 生成过程不调用模型、不修改策略，所以无需伪造第二次确认框；
                # CSRF 保护和一次明确点击已经表达本次意图。
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                try:
                    body = await request.json()
                except (ValueError, UnicodeError):
                    raise web.HTTPBadRequest() from None
                if body != {}:
                    raise web.HTTPBadRequest()
                result = await asyncio.to_thread(
                    backend.generate_companion_strategy_candidate,
                )
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get(
        "/api/companion-strategy-candidates", strategy_candidates,
        allow_head=False,
    )
    app.router.add_post(
        "/api/companion-strategy-candidates/analyze", strategy_candidates,
    )

    async def user_initiated_interactions(request):
        raw_limit = request.query.get("limit", "30")
        try:
            limit = int(raw_limit)
            if str(limit) != raw_limit:
                raise ValueError
            result = await asyncio.to_thread(
                backend.list_user_initiated_interactions, limit=limit,
            )
            return web.json_response(result)
        except ValueError:
            raise web.HTTPBadRequest() from None
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get(
        "/api/companion-user-initiated-interactions",
        user_initiated_interactions,
        allow_head=False,
    )

    async def dismiss_strategy_candidate(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = CompanionStrategyDismissRequest.model_validate(
                await request.json()
            )
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        try:
            result = await asyncio.to_thread(
                backend.dismiss_companion_strategy_candidate,
                request.match_info["candidate_id"],
                expected_revision=body.expected_revision,
            )
            return web.json_response(result)
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    app.router.add_post(
        r"/api/companion-strategy-candidates/{candidate_id:[0-9a-f]{32}}/dismiss",
        dismiss_strategy_candidate,
    )
