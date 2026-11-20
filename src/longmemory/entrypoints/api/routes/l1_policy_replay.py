"""L1 充分性本地策略回放；沿用控制台会话与 CSRF 防护。"""

import asyncio

from aiohttp import web

from ..errors import ExperimentError


def register_l1_policy_replay_routes(app, get_backend):
    async def dispatch(request):
        backend = get_backend()
        try:
            if request.method == "GET":
                result = await asyncio.to_thread(
                    backend.l1_policy_replay_options,
                )
            else:
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                body = await request.clone(client_max_size=4096).json()
                result = await asyncio.to_thread(
                    backend.run_l1_policy_replay, body,
                )
            return web.json_response(result)
        except ExperimentError as error:
            return web.json_response({"error": error.code}, status=error.status)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return web.json_response({"error": "l1_policy_replay_unreadable"}, status=400)

    app.router.add_get(
        "/api/l1-policy-replay", dispatch, allow_head=False,
    )
    app.router.add_post("/api/l1-policy-replay", dispatch)
