"""本机控制台入口。只提供白名单资源；记忆库必须由启动参数明确选择。"""

import argparse
import asyncio
import os
from pathlib import Path
import re

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
from .routes.memory_runtime import register_memory_runtime_routes
from .routes.memory_mode import register_memory_mode_routes
from .device_role import DeviceRole
from .voice_settings import VoiceSettings, register_voice_routes
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging

ROOT = Path(__file__).resolve().parents[4]
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/memories-legacy": ("memories.html", "text/html"),
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


def create_app(*, port=8765, bridge=None, web_root=None, database=None, allow_memory_delete=False,
               allow_memory_correction=False, allow_scenario_management=False,
               allow_persona_management=False,
               chat_backend=None, experiment_backend=None, job_backend=None, instance_id=None,
               xiaozhi_server=None, memory_runtime_token=None, scenario_producer=None,
               scenario_model=None, persona_producer=None, persona_model=None,
               consolidation_background_enabled=False):
    sessions = Sessions()
    assets = web_root or ROOT / "web"
    client = bridge if bridge is not None else XiaozhiControlClient(ROOT / "data/control/device-control.token")
    operation_lock = asyncio.Lock()
    app = web.Application(client_max_size=1024, middlewares=[
        security_middleware(f"127.0.0.1:{port}", sessions, memory_runtime_token)
    ])

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
    register_memory_routes(app, MemoryBackend(
        database,
        allow_delete=allow_memory_delete,
        allow_correction=allow_memory_correction,
        allow_scenario_management=allow_scenario_management,
        allow_persona_management=allow_persona_management,
        scenario_producer=scenario_producer,
        scenario_model=scenario_model,
        persona_producer=persona_producer,
        persona_model=persona_model,
        consolidation_background_enabled=consolidation_background_enabled,
    ))
    register_chat_routes(app, chat_backend)
    register_memory_mode_routes(app, chat_backend)
    if memory_runtime_token:
        register_memory_runtime_routes(app, chat_backend)
    device_role = DeviceRole(xiaozhi_server, chat_backend.roles, chat_backend.database, ROOT) if xiaozhi_server and chat_backend else None
    register_role_routes(app, chat_backend, device_role)
    register_voice_routes(app, VoiceSettings(xiaozhi_server, chat_backend.database, ROOT) if xiaozhi_server and chat_backend else None)
    experiments = experiment_backend if experiment_backend is not None else ExperimentBackend(ROOT / "experiments")
    register_experiment_routes(app, experiments)
    register_job_routes(app, job_backend if job_backend is not None else ExperimentJobs(experiments))
    app.on_cleanup.append(close)
    return app


def main():
    parser = argparse.ArgumentParser(description="LongMemory 本机控制台（不会自动启动小智）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, help="已有当前版本记忆数据库；不自动建库或迁移")
    parser.add_argument("--allow-memory-delete", action="store_true", help="启用网页单条删除；默认只读")
    parser.add_argument("--allow-memory-correction", action="store_true", help="启用网页人工纠正；旧记忆保留并标记为已取代")
    parser.add_argument("--allow-scenario-management", action="store_true", help="启用显式 L2 候选创建与复核；默认只读")
    parser.add_argument("--allow-persona-management", action="store_true", help="启用显式 L3 候选创建与复核；默认只读")
    parser.add_argument("--enable-chat", action="store_true", help="允许网页向指定已有记忆库写入对话和记忆")
    parser.add_argument(
        "--enable-memory-consolidation", action="store_true",
        help="显式启用单一后台 L1→L2→L3 整理；默认关闭并且不会扫描数据库",
    )
    parser.add_argument("--memory-audit-log", type=Path, help="共享记忆 Runtime 的脱敏审计日志")
    parser.add_argument("--chat-provider", choices=("fake", "openai_compatible"), default="fake")
    parser.add_argument("--memory-extraction", choices=("rules", "llm"), default="rules",
                        help="日常 L1 提取策略；llm 失败时保留 L0 并显式标记")
    parser.add_argument("--memory-retrieval", choices=("keyword", "hybrid"), default="keyword",
                        help="日常召回策略；hybrid 使用本地固定 BGE 快照")
    parser.add_argument("--embedding-model-dir", type=Path,
                        help="hybrid 使用的已校验本地 BGE 快照目录")
    parser.add_argument("--assistant-role", choices=("plain_v1", "elysia_v1"), default="plain_v1")
    parser.add_argument("--xiaozhi-server", type=Path, help="允许用户确认后同步角色到此小智目录；不会自动修改配置或重启")
    parser.add_argument("--enable-experiment-runs", action="store_true", help="允许网页确认后运行冻结检索回答对照；默认只读实验")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 必须在 1024–65535 之间")
    if args.allow_memory_delete and args.database is None:
        parser.error("启用删除前必须用 --database 指定已有数据库")
    if args.allow_memory_correction and args.database is None:
        parser.error("启用纠正前必须用 --database 指定已有数据库")
    if args.allow_persona_management and args.database is None:
        parser.error("启用 L3 画像管理前必须用 --database 指定已有数据库")
    if args.enable_chat and args.database is None:
        parser.error("启用文字聊天前必须用 --database 指定已有数据库")
    if args.memory_audit_log and not args.enable_chat:
        parser.error("记忆审计日志仅在启用文字聊天/共享 Runtime 时有效")
    if args.enable_memory_consolidation and not args.enable_chat:
        parser.error("后台记忆整理只能由启用文字聊天的共享 Runtime 单一拥有")
    if args.enable_memory_consolidation and args.chat_provider != "openai_compatible":
        parser.error("后台记忆整理需要 openai_compatible 候选生成与独立风险复核")
    if args.memory_extraction == "llm" and not args.enable_chat:
        parser.error("模型辅助提取仅在启用文字聊天/共享 Runtime 时有效")
    if args.memory_retrieval == "hybrid" and not args.enable_chat:
        parser.error("混合召回仅在启用文字聊天/共享 Runtime 时有效")
    if args.memory_extraction == "llm" and args.chat_provider != "openai_compatible":
        parser.error("模型辅助提取需要 openai_compatible 配置；Fake 只用于离线回答测试")
    if (args.memory_retrieval == "hybrid") != (args.embedding_model_dir is not None):
        parser.error("hybrid 必须且只有 hybrid 可以指定 --embedding-model-dir")
    chat_backend = None
    job_backend = None
    scenario_producer = None
    scenario_model = None
    persona_producer = None
    persona_model = None
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
        from longmemory.adapters.llm.candidate_extractor import OpenAICompatibleCandidateProducer
        from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
        from longmemory.application.memory_runtime import MemoryRuntime
        from longmemory.adapters.storage.sqlite_scenario_recall import SQLiteScenarioRecallProvider
        from longmemory.adapters.storage.sqlite_persona_recall import SQLitePersonaRecallProvider
        from longmemory.adapters.storage.sqlite_natural_memory_commands import SQLiteNaturalMemoryCommandHandler
        from longmemory.core.memory.retrieval.service import HybridMemoryRetriever
        from longmemory.infrastructure.config.settings import load_model_settings
        from longmemory.methods.daily_llm.method import DailyLLMMemory
        from longmemory.methods.longmemory_v1.method import LongMemoryV1
        from .chat_backend import ChatBackend
        consolidation_scheduler = None
        runtime = None
        try:
            # 只读预检；不能为了打开网页而创建或迁移用户的记忆库。
            MemoryBackend(args.database).list_page(limit=1)
            settings = load_model_settings(provider=args.chat_provider)
            role_prompt = (ROOT / "src/longmemory/prompts/personas" / (args.assistant_role + ".txt")).read_text(encoding="utf-8")
            role_prompt = role_prompt.replace("<memory></memory>", "（证据见独立 memory_evidence 消息。）")
            generator = (FakeAnswerGenerator() if settings.provider == "fake" else
                         OpenAICompatibleAnswerGenerator(settings, role_prompt=role_prompt))
            if args.enable_memory_consolidation:
                from longmemory.adapters.llm.consolidation_risk import (
                    OpenAICompatibleConsolidationRiskReviewer,
                )
                from longmemory.adapters.llm.persona_candidate import (
                    OpenAICompatiblePersonaProposalProducer,
                    PERSONA_CONSOLIDATION_PROMPT_VERSION,
                )
                from longmemory.adapters.llm.scenario_candidate import (
                    OpenAICompatibleScenarioProposalProducer,
                    SCENARIO_PROMPT_VERSION,
                )
                from longmemory.application.consolidation.cycle import (
                    LowFrequencyConsolidationCycle,
                )
                from longmemory.application.consolidation.scheduler import (
                    LowFrequencyConsolidationScheduler,
                )
                cycle = LowFrequencyConsolidationCycle(
                    database=args.database,
                    scenario_producer=OpenAICompatibleScenarioProposalProducer(settings),
                    persona_producer=OpenAICompatiblePersonaProposalProducer(settings),
                    risk_reviewer=OpenAICompatibleConsolidationRiskReviewer(settings),
                    generator_name=settings.model,
                    scenario_generator_version=SCENARIO_PROMPT_VERSION,
                    persona_generator_version=PERSONA_CONSOLIDATION_PROMPT_VERSION,
                )
                consolidation_scheduler = LowFrequencyConsolidationScheduler(
                    subject_id="user:self", run_cycle=cycle, enabled=True,
                )
            retriever_factory = None
            if args.memory_retrieval == "hybrid":
                from longmemory.adapters.llm.local_embedding import LocalBGEEncoder
                encoder = LocalBGEEncoder(args.embedding_model_dir)
                retriever_factory = lambda store: HybridMemoryRetriever(store, encoder)
            if args.memory_extraction == "llm":
                method = DailyLLMMemory(
                    args.database,
                    producer=OpenAICompatibleCandidateProducer(settings),
                    existing_only=True,
                    allow_cross_thread=True,
                    retriever_factory=retriever_factory,
                )
                runtime = MemoryRuntime(args.database, method=method,
                                        scenario_provider=SQLiteScenarioRecallProvider(args.database),
                                        persona_provider=SQLitePersonaRecallProvider(args.database),
                                        memory_command_handler=SQLiteNaturalMemoryCommandHandler(args.database),
                                        consolidation_scheduler=consolidation_scheduler)
            elif retriever_factory is not None:
                method = LongMemoryV1(
                    args.database, existing_only=True, allow_cross_thread=True,
                    retriever_factory=retriever_factory,
                )
                runtime = MemoryRuntime(args.database, method=method,
                                        scenario_provider=SQLiteScenarioRecallProvider(args.database),
                                        persona_provider=SQLitePersonaRecallProvider(args.database),
                                        memory_command_handler=SQLiteNaturalMemoryCommandHandler(args.database),
                                        consolidation_scheduler=consolidation_scheduler)
            else:
                method = LongMemoryV1(
                    args.database, existing_only=True, allow_cross_thread=True,
                )
                runtime = MemoryRuntime(
                    args.database, method=method,
                    scenario_provider=SQLiteScenarioRecallProvider(args.database),
                    persona_provider=SQLitePersonaRecallProvider(args.database),
                    memory_command_handler=SQLiteNaturalMemoryCommandHandler(args.database),
                    consolidation_scheduler=consolidation_scheduler,
                )
            chat_backend = ChatBackend(args.database, generator, provider=settings.provider,
                                       model=settings.model or "fake", role=args.assistant_role,
                                       runtime=runtime)
            if args.allow_scenario_management and settings.provider == "openai_compatible":
                from longmemory.adapters.llm.scenario_candidate import OpenAICompatibleScenarioProposalProducer
                scenario_producer = OpenAICompatibleScenarioProposalProducer(settings)
                scenario_model = settings.model
            if args.allow_persona_management and settings.provider == "openai_compatible":
                from longmemory.adapters.llm.persona_candidate import OpenAICompatiblePersonaProposalProducer
                persona_producer = OpenAICompatiblePersonaProposalProducer(settings)
                persona_model = settings.model
        except Exception:
            if runtime is not None:
                runtime.close()
            elif consolidation_scheduler is not None:
                consolidation_scheduler.close()
            parser.error("文字聊天配置无效：请检查已有数据库版本、模型环境变量和角色文件。未建库或迁移。")
        if settings.base_url.startswith("http://"):
            print("警告：模型 HTTP 会明文传输凭据、对话和检索证据；仅用于已确认风险的校园网合成体验。")
    if not all((ROOT / "web" / path).is_file() for path, _mime in STATIC_FILES.values()):
        parser.error("控制台静态资源缺失；当前入口需要从完整源代码仓库可编辑安装后启动")
    runtime_token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN")
    if runtime_token is not None and re.fullmatch(r"[0-9a-f]{64}", runtime_token) is None:
        parser.error("LONGMEMORY_RUNTIME_TOKEN 必须是启动器生成的 64 位小写十六进制值")
    print(f"控制台：http://127.0.0.1:{args.port}；仅本机访问，Ctrl+C 停止。")
    if args.database:
        capabilities = []
        if args.allow_memory_correction:
            capabilities.append("允许人工纠正（旧记录保留）")
        if args.allow_memory_delete:
            capabilities.append("允许单条删除（L0 保留）")
        if args.allow_persona_management:
            capabilities.append("允许 L3 候选与复核")
        print(f"记忆库：{args.database.resolve()}；管理页" + ("、".join(capabilities) if capabilities else "只读"))
    if chat_backend:
        extraction = "模型辅助（失败保留 L0）" if args.memory_extraction == "llm" else "规则基线"
        retrieval = "关键词＋本地 BGE 融合" if args.memory_retrieval == "hybrid" else "关键词基线"
        print(f"文字聊天已启用：{args.chat_provider} / {args.assistant_role}；L1 提取={extraction}，召回={retrieval}，不驱动圆屏播音。")
    audit_handler = configure_file_logging(args.memory_audit_log) if args.memory_audit_log else None
    try:
        web.run_app(create_app(port=args.port, database=args.database, allow_memory_delete=args.allow_memory_delete,
                               allow_memory_correction=args.allow_memory_correction,
                               allow_scenario_management=args.allow_scenario_management,
                               allow_persona_management=args.allow_persona_management,
                               chat_backend=chat_backend, job_backend=job_backend,
                               instance_id=os.environ.get("LONGMEMORY_LAUNCHER_INSTANCE"), xiaozhi_server=args.xiaozhi_server,
                               memory_runtime_token=runtime_token,
                               scenario_producer=scenario_producer, scenario_model=scenario_model,
                               persona_producer=persona_producer, persona_model=persona_model,
                               consolidation_background_enabled=args.enable_memory_consolidation),
                    host="127.0.0.1", port=args.port, access_log=None, print=None)
    except OSError:
        parser.exit(1, f"控制台未能绑定 127.0.0.1:{args.port}。请检查旧控制台是否仍在运行或端口权限；未自动停止其他进程、未换端口。\n")
    finally:
        if chat_backend is not None:
            chat_backend.close()
        if audit_handler is not None:
            close_file_logging(audit_handler)


if __name__ == "__main__":
    main()
