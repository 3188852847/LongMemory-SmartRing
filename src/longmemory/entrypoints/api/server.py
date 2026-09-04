"""本机控制台入口。只提供白名单资源；记忆库必须由启动参数明确选择。"""

import argparse
import asyncio
import os
from pathlib import Path

from aiohttp import web

from longmemory.adapters.device_control.xiaozhi import BridgeError, XiaozhiControlClient
from .security import COOKIE, MAX_AGE, Sessions, security_middleware
from .memory_backend import MemoryBackend
from .routes.memories import register_memory_routes
from .routes.chat import register_chat_routes
from .routes.experiments import register_experiment_routes
from .experiment_backend import ExperimentBackend
from .experiment_jobs import ExperimentJobs
from .routes.experiment_jobs import register_job_routes
from .react_assets import register_react_routes
from .routes.assistant_role import register_role_routes

ROOT = Path(__file__).resolve().parents[4]
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/memories": ("memories.html", "text/html"),
    "/chat": ("chat.html", "text/html"),
    "/experiments": ("experiments.html", "text/html"),
    "/assets/experiments.js": ("assets/experiments.js", "text/javascript"),
    "/assets/experiment-jobs.mjs": ("assets/experiment-jobs.mjs", "text/javascript"),
    "/assets/experiment-view.mjs": ("assets/experiment-view.mjs", "text/javascript"),
    "/assets/experiments.css": ("assets/experiments.css", "text/css"),
    "/assets/chat.js": ("assets/chat.js", "text/javascript"),
    "/assets/appearance.js": ("assets/appearance.js", "text/javascript"),
    "/assets/appearance.mjs": ("assets/appearance.mjs", "text/javascript"),
    "/assets/chat-appearance.css": ("assets/chat-appearance.css", "text/css"),
    "/assets/chat-view.mjs": ("assets/chat-view.mjs", "text/javascript"),
    "/assets/console.css": ("assets/console.css", "text/css"),
    "/assets/app.js": ("assets/app.js", "text/javascript"),
    "/assets/state.mjs": ("assets/state.mjs", "text/javascript"),
    "/assets/memories.js": ("assets/memories.js", "text/javascript"),
    "/assets/memory-view.mjs": ("assets/memory-view.mjs", "text/javascript"),
    "/assets/favicon.svg": ("assets/favicon.svg", "image/svg+xml"),
}


def create_app(*, port=8765, bridge=None, web_root=None, database=None, allow_memory_delete=False, chat_backend=None, experiment_backend=None, job_backend=None, instance_id=None):
    sessions = Sessions()
    assets = web_root or ROOT / "web"
    client = bridge if bridge is not None else XiaozhiControlClient(ROOT / "data/control/device-control.token")
    operation_lock = asyncio.Lock()
    app = web.Application(client_max_size=1024, middlewares=[security_middleware(f"127.0.0.1:{port}", sessions)])

    async def static(request):
        # 不把仓库当作静态文件目录，避免 .env、数据库和令牌被网页下载。
        filename, mime = STATIC_FILES[request.path]
        response = web.Response(body=(assets / filename).read_bytes(), content_type=mime)
        # 启动器只用随机实例标识核对就绪，不承担认证，也不泄漏模型配置。
        if instance_id:
            response.headers["X-LongMemory-Instance"] = instance_id
        return response

    async def session(request):
        # 自定义头不能由跨源 HTML 表单发出；没有 CORS 放行预检。
        if request.headers.get("X-Console-Bootstrap") != "1":
            return web.json_response({"error": "bootstrap_required"}, status=403)
        old_session = request.cookies.get(COOKIE)
        csrf = sessions.csrf(old_session)
        session_id, csrf = (old_session, csrf) if csrf else sessions.create()
        response = web.json_response({"csrf": csrf})
        response.set_cookie(COOKIE, session_id, httponly=True, samesite="Strict", max_age=MAX_AGE, path="/")
        return response

    async def device(request):
        try:
            return web.json_response(await client.status())
        except BridgeError as error:
            return web.json_response({"error": error.code}, status=error.status)

    async def volume(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        async with operation_lock:
            try:
                if request.method == "GET":
                    data = await client.read_volume()
                else:
                    if request.content_type != "application/json":
                        return web.json_response({"error": "invalid_body"}, status=400)
                    try:
                        body = await request.json()
                    except (ValueError, UnicodeError):
                        return web.json_response({"error": "invalid_body"}, status=400)
                    if (not isinstance(body, dict) or set(body) != {"volume"}
                            or type(body["volume"]) is not int or not 5 <= body["volume"] <= 60):
                        return web.json_response({"error": "invalid_volume"}, status=400)
                    data = await client.set_volume(body["volume"])
                return web.json_response(data)
            except BridgeError as error:
                return web.json_response({"error": error.code}, status=error.status)

    async def close(_app):
        await client.close()

    for path in STATIC_FILES:
        app.router.add_get(path, static)
    register_react_routes(app, assets / 'react-chat/dist')
    app.router.add_get("/api/session", session, allow_head=False)
    app.router.add_get("/api/device", device, allow_head=False)
    app.router.add_get("/api/device/volume", volume, allow_head=False)
    app.router.add_post("/api/device/volume", volume)
    register_memory_routes(app, MemoryBackend(database, allow_delete=allow_memory_delete))
    register_chat_routes(app, chat_backend)
    register_role_routes(app, chat_backend)
    experiments = experiment_backend if experiment_backend is not None else ExperimentBackend(ROOT / "experiments")
    register_experiment_routes(app, experiments)
    register_job_routes(app, job_backend if job_backend is not None else ExperimentJobs(experiments))
    app.on_cleanup.append(close)
    return app


def main():
    parser = argparse.ArgumentParser(description="LongMemory 本机控制台（不会自动启动小智）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, help="已有 V3 记忆数据库；不自动建库或迁移")
    parser.add_argument("--allow-memory-delete", action="store_true", help="启用网页单条删除；默认只读")
    parser.add_argument("--enable-chat", action="store_true", help="允许网页向指定已有记忆库写入对话和记忆")
    parser.add_argument("--chat-provider", choices=("fake", "openai_compatible"), default="fake")
    parser.add_argument("--assistant-role", choices=("plain_v1", "elysia_v1"), default="plain_v1")
    parser.add_argument("--enable-experiment-runs", action="store_true", help="允许网页确认后运行冻结检索回答对照；默认只读实验")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 必须在 1024–65535 之间")
    if args.allow_memory_delete and args.database is None:
        parser.error("启用删除前必须用 --database 指定已有数据库")
    if args.enable_chat and args.database is None:
        parser.error("启用文字聊天前必须用 --database 指定已有数据库")
    chat_backend = None
    job_backend = None
    if args.enable_experiment_runs:
        from longmemory.infrastructure.config.settings import load_model_settings
        try:
            experiment_settings = load_model_settings(provider="openai_compatible")
        except ValueError:
            experiment_settings = None
        job_backend = ExperimentJobs(ExperimentBackend(ROOT / "experiments"), enabled=True, settings=experiment_settings)
        print("实验作业已启用；仅用户在网页预检并确认后执行。" +
              ("兼容模型配置可用（未联网验证）。" if experiment_settings else "未配置兼容模型，目前仅能运行 Fake。"))
    if args.enable_chat:
        from longmemory.adapters.llm.fake import FakeAnswerGenerator
        from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
        from longmemory.infrastructure.config.settings import load_model_settings
        from .chat_backend import ChatBackend
        try:
            # 只读预检；不能为了打开网页而创建或迁移用户的记忆库。
            MemoryBackend(args.database).list_page(limit=1)
            settings = load_model_settings(provider=args.chat_provider)
            role_prompt = (ROOT / "src/longmemory/prompts/personas" / (args.assistant_role + ".txt")).read_text(encoding="utf-8")
            role_prompt = role_prompt.replace("<memory></memory>", "（证据见独立 memory_evidence 消息。）")
            generator = (FakeAnswerGenerator() if settings.provider == "fake" else
                         OpenAICompatibleAnswerGenerator(settings, role_prompt=role_prompt))
            chat_backend = ChatBackend(args.database, generator, provider=settings.provider,
                                       model=settings.model or "fake", role=args.assistant_role)
        except Exception:
            parser.error("文字聊天配置无效：请检查已有数据库版本、模型环境变量和角色文件。未建库或迁移。")
        if settings.base_url.startswith("http://"):
            print("警告：模型 HTTP 会明文传输凭据、对话和检索证据；仅用于已确认风险的校园网合成体验。")
    if not all((ROOT / "web" / path).is_file() for path, _mime in STATIC_FILES.values()):
        parser.error("控制台静态资源缺失；当前入口需要从完整源代码仓库可编辑安装后启动")
    print(f"控制台：http://127.0.0.1:{args.port}；仅本机访问，Ctrl+C 停止。")
    if args.database:
        print(f"记忆库：{args.database.resolve()}；管理页" + ("允许单条删除（L0 保留）" if args.allow_memory_delete else "只读"))
    if chat_backend:
        print(f"文字聊天已启用：{args.chat_provider} / {args.assistant_role}；会写入 L0/L1，不驱动圆屏播音。")
    try:
        web.run_app(create_app(port=args.port, database=args.database, allow_memory_delete=args.allow_memory_delete, chat_backend=chat_backend, job_backend=job_backend,
                               instance_id=os.environ.get("LONGMEMORY_LAUNCHER_INSTANCE")),
                    host="127.0.0.1", port=args.port, access_log=None, print=None)
    except OSError:
        parser.exit(1, f"控制台未能绑定 127.0.0.1:{args.port}。请检查旧控制台是否仍在运行或端口权限；未自动停止其他进程、未换端口。\n")


if __name__ == "__main__":
    main()
