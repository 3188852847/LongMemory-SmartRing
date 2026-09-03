"""运行入口与原报告路由分开，沿用会话、同源和 CSRF 检查。"""
import asyncio
from aiohttp import web
from ..experiment_backend import ExperimentError
from ..security import COOKIE


def register_job_routes(app, backend):
    async def dispatch(request):
        try:
            if request.method == "GET":
                fn = backend.options if request.path.endswith("/options") else backend.listing
                result = await asyncio.to_thread(fn)
            else:
                if request.content_type != "application/json":
                    raise web.HTTPBadRequest()
                body = await request.clone(client_max_size=4096).json()
                if request.path.endswith("/stop"):
                    if body != {}:
                        raise web.HTTPBadRequest()
                    result = await asyncio.to_thread(backend.stop, request.match_info["job_id"])
                else:
                    fn = backend.prepare if request.path.endswith("/prepare") else backend.start
                    result = await asyncio.to_thread(fn, body, request.cookies.get(COOKIE))
            return web.json_response(result)
        except ExperimentError as error:
            return web.json_response({"error": error.code}, status=error.status)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return web.json_response({"error": "job_input_or_storage_invalid"}, status=400)

    app.router.add_get("/api/experiment-jobs/options", dispatch, allow_head=False)
    app.router.add_get("/api/experiment-jobs", dispatch, allow_head=False)
    app.router.add_post("/api/experiment-jobs/prepare", dispatch)
    app.router.add_post("/api/experiment-jobs/start", dispatch)
    app.router.add_post("/api/experiment-jobs/{job_id}/stop", dispatch)

    async def cleanup(_app):
        await asyncio.to_thread(backend.close)
    app.on_cleanup.append(cleanup)
