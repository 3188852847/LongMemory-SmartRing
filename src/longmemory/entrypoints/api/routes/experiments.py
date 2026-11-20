"""实验只读接口和窄范围人工复核写入口，沿用本机会话与 CSRF 防护。"""
import asyncio
from aiohttp import web
from ..errors import ExperimentError
from .experiment_jobs import register_job_routes
from .l1_policy_replay import register_l1_policy_replay_routes


def register_research_routes(app, root, experiments=None, jobs=None):
    # 在事件循环内首次访问时装配，同一控制台的所有研究请求共用实例。
    def archive():
        nonlocal experiments
        if experiments is None:
            from ..experiment_backend import ExperimentBackend
            experiments = ExperimentBackend(root)
        return experiments

    def job_service():
        nonlocal jobs
        if jobs is None:
            from ..experiment_jobs import ExperimentJobs
            jobs = ExperimentJobs(archive())
        return jobs

    async def close(_app):
        if jobs is not None:
            await asyncio.to_thread(jobs.close)

    app.on_cleanup.append(close)
    register_job_routes(app, job_service)
    register_l1_policy_replay_routes(app, archive)

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
        return await invoke(archive().listing)

    async def detail(request):
        return await invoke(archive().detail, request.match_info["run_id"])

    async def question(request):
        if set(request.query) != {"id"} or len(request.query.getall("id")) != 1:
            raise web.HTTPBadRequest()
        return await invoke(archive().question, request.match_info["run_id"], request.query["id"])

    async def save(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.clone(client_max_size=16384).json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        return await invoke(archive().save_review, request.match_info["run_id"], body)

    app.router.add_get("/api/experiments", listing, allow_head=False)
    app.router.add_get("/api/experiments/{run_id}", detail, allow_head=False)
    app.router.add_get("/api/experiments/{run_id}/question", question, allow_head=False)
    app.router.add_post("/api/experiments/{run_id}/reviews", save)
