"""实验只读接口和窄范围人工复核写入口，沿用本机会话与 CSRF 防护。"""
import asyncio
from aiohttp import web
from ..experiment_backend import ExperimentError


def register_experiment_routes(app, backend):
    async def invoke(function, *args):
        try:
            return web.json_response(await asyncio.to_thread(function, *args))
        except ExperimentError as error:
            return web.json_response({"error": error.code}, status=error.status)
        except FileNotFoundError:
            return web.json_response({"error": "experiment_not_found"}, status=404)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return web.json_response({"error": "experiment_unreadable"}, status=400)

    async def listing(request):
        return await invoke(backend.listing)

    async def detail(request):
        return await invoke(backend.detail, request.match_info["run_id"])

    async def question(request):
        if set(request.query) != {"id"} or len(request.query.getall("id")) != 1:
            raise web.HTTPBadRequest()
        return await invoke(backend.question, request.match_info["run_id"], request.query["id"])

    async def save(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.clone(client_max_size=16384).json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        return await invoke(backend.save_review, request.match_info["run_id"], body)

    app.router.add_get("/api/experiments", listing, allow_head=False)
    app.router.add_get("/api/experiments/{run_id}", detail, allow_head=False)
    app.router.add_get("/api/experiments/{run_id}/question", question, allow_head=False)
    app.router.add_post("/api/experiments/{run_id}/reviews", save)
