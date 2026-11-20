"""本机控制台入口。只提供白名单资源；记忆库必须由启动参数明确选择。"""

import argparse
import asyncio
import os
from pathlib import Path
import re

from aiohttp import web

from longmemory.adapters.device_control.xiaozhi import XiaozhiControlClient
from .security import COOKIE, MAX_AGE, Sessions, security_middleware
from .routes.chat import register_chat_routes
from .react_assets import register_react_routes
from .otto_preview import register_otto_preview
from .routes.assistant_role import register_role_routes
from .routes.memory_runtime import register_memory_runtime_routes
from .routes.memory_mode import register_memory_mode_routes
from .routes.model_profiles import register_model_profile_routes
from .xiaozhi_model_profiles import XiaozhiModelProfiles
from .routes.tts_backends import register_tts_backend_routes
from .routes.device import register_device_routes
from .routes.round_skins import register_round_skin_routes
from longmemory.infrastructure.config.round_skins import RoundSkinStore
from .routes.round_wallpapers import register_round_wallpaper_routes
from longmemory.infrastructure.media.round_wallpaper_library import RoundWallpaperLibrary
from longmemory.infrastructure.media.round_wallpaper_delivery import RoundWallpaperDeliveryService
from .device_role import DeviceRole
from .voice_settings import VoiceSettings, register_voice_routes
from .vad_settings import VadSettings, register_vad_routes
from .launcher_status import read_launcher_status
from longmemory.infrastructure.logging.setup import configure_file_logging, close_file_logging
from longmemory.infrastructure.logging.diagnostics import Diagnostics
from .observability import observability_middleware, register_observability

ROOT = Path(__file__).resolve().parents[4]
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/chat": ("chat.html", "text/html"),
    "/assets/chat.js": ("assets/chat.js", "text/javascript"),
    "/assets/appearance.js": ("assets/appearance.js", "text/javascript"),
    "/assets/appearance.mjs": ("assets/appearance.mjs", "text/javascript"),
    "/assets/chat-appearance.css": ("assets/chat-appearance.css", "text/css"),
    "/assets/chat-view.mjs": ("assets/chat-view.mjs", "text/javascript"),
    "/assets/console.css": ("assets/console.css", "text/css"),
    "/assets/app.js": ("assets/app.js", "text/javascript"),
    "/assets/state.mjs": ("assets/state.mjs", "text/javascript"),
    "/assets/favicon.svg": ("assets/favicon.svg", "image/svg+xml"),
}


def create_app(*, port=8765, bridge=None, web_root=None, allow_memory_delete=False,
               allow_memory_correction=False,
               chat_backend=None, instance_id=None,
               xiaozhi_server=None, memory_runtime_token=None,
               model_profile_store=None, voice_model_profiles=None,
               tts_backend_store=None,
               round_skin_store=None, round_wallpaper_library=None,
               round_wallpaper_delivery=None, launcher_status_file=None,
               diagnostics=None, observability_root=None,
               otto_asset_root=None, memory_runtime=None,
               voice_proposals_enabled=False, voice_proposal_host=None, qq_directory=None):
    # 显式新后端必须同时支配聊天和管理，禁止管理悄悄打开另一套旧库。
    if memory_runtime is not None and chat_backend is not None:
        if chat_backend.memory_runtime() is not memory_runtime:
            raise ValueError("chat_and_management_runtime_mismatch")
    runtime = memory_runtime or (getattr(chat_backend, "_runtime", None) if chat_backend else None)
    from .routes.qq_memory import qq_token, register_qq_memory
    sessions = Sessions()
    assets = web_root or ROOT / "web"
    client = bridge if bridge is not None else XiaozhiControlClient(ROOT / "data/control/device-control.token")
    operation_lock = asyncio.Lock()
    observer = diagnostics if diagnostics is not None else Diagnostics(observability_root)
    from .network_maintenance import NetworkMaintenance, owned_runtime_idle, PATH as MAINTENANCE_PATH
    maintenance = NetworkMaintenance(instance_id)
    app = web.Application(client_max_size=1024, middlewares=[
        observability_middleware(observer),
        security_middleware(f"127.0.0.1:{port}", sessions, memory_runtime_token,
                            qq_token=qq_token(qq_directory) if qq_directory else None),
        maintenance.middleware,
    ])
    if qq_directory and runtime is not None:
        register_qq_memory(app, runtime, qq_directory)
        from .routes.companion_outreach import register_outreach
        register_outreach(app, runtime, qq_directory, client)
    app.router.add_post(MAINTENANCE_PATH, maintenance.handle)
    register_observability(app, observer)

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

    async def runtime_status(request):
        return web.json_response(read_launcher_status(
            launcher_status_file,
            instance_id,
        ))

    def current_runtime_status():
        return read_launcher_status(launcher_status_file, instance_id)

    async def close(_app):
        await client.close()

    for path in STATIC_FILES:
        app.router.add_get(path, static)
    register_react_routes(app, assets / 'react-chat/dist')
    async def whale_animation(request):
        directory = ROOT / 'data/round-screen/whale'
        if request.path.startswith('/pet/whale/device/'):
            directory = directory / 'device'
        path = directory / (request.match_info['face'] + '.gif')
        if path.is_symlink() or directory.resolve() != directory or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)
    app.router.add_get(r'/pet/whale/device/{face:neutral|happy|thinking|sleep|wink}.gif', whale_animation)
    app.router.add_get(r'/pet/whale/{face:neutral|happy|listening|thinking|speaking|sleep|wink}.gif', whale_animation)
    app.router.add_get("/api/session", session, allow_head=False)
    register_otto_preview(app, otto_asset_root)
    app.router.add_get("/api/runtime-status", runtime_status, allow_head=False)
    register_device_routes(app, client, operation_lock)
    from .routes.memory_engine import register_memory_engine_routes
    def selected_memory_runtime():
        selected = runtime or (chat_backend.memory_runtime() if chat_backend else None)
        if selected is None:
            from .errors import MemoryAccessError
            raise MemoryAccessError("memory_runtime_unavailable", 503)
        return selected
    def existing_memory_runtime():
        return runtime or (getattr(chat_backend, "_runtime", None) if chat_backend else None)
    register_memory_engine_routes(app, selected_memory_runtime, allow_delete=allow_memory_delete,
                                  allow_correction=allow_memory_correction,
                                  snapshot_runtime=existing_memory_runtime)
    from .routes.memory_identity import register_memory_identity_route
    register_memory_identity_route(app, existing_memory_runtime)
    chat_idle = register_chat_routes(app, chat_backend)
    maintenance.idle_checks.extend([chat_idle, lambda: not operation_lock.locked(), lambda: owned_runtime_idle(runtime)])
    register_memory_mode_routes(app, chat_backend)
    if memory_runtime_token:
        register_memory_runtime_routes(app, chat_backend)
        # 与3.10小智共享的仅是受信内部RPC，宿主模型/预算/记忆对象留在3.12。
        from longmemory.application.voice_proposals import VoiceProposalHost
        from .routes.voice_proposals import register_voice_proposal_routes
        proposal_host = voice_proposal_host or VoiceProposalHost(
            existing_memory_runtime, enabled=voice_proposals_enabled)
        register_voice_proposal_routes(app, proposal_host)
    device_role = DeviceRole(xiaozhi_server, chat_backend.roles, chat_backend.sidecar_database, ROOT) if xiaozhi_server and chat_backend else None
    from .routes.companion import register_companion
    register_companion(app, ROOT / "local/runtime/companion")
    register_role_routes(app, chat_backend, device_role)
    register_voice_routes(app, VoiceSettings(xiaozhi_server, chat_backend.sidecar_database, ROOT) if xiaozhi_server and chat_backend else None)
    register_vad_routes(app, VadSettings(
        xiaozhi_server, ROOT, launcher_status_file, instance_id,
    ) if xiaozhi_server and chat_backend else None)
    register_tts_backend_routes(app, tts_backend_store, current_runtime_status)
    voice_profiles = voice_model_profiles or (
        XiaozhiModelProfiles(ROOT, xiaozhi_server, model_profile_store,
            model_settings_factory=(lambda: runtime.external_model_settings("answer")) if runtime is not None else None)
        if xiaozhi_server and model_profile_store else None
    )
    service = getattr(runtime, "_model_service", None)
    live = getattr(service, "apply_campus_connection", None) if getattr(model_profile_store, "current_profile", None) == "campus" else None
    register_model_profile_routes(app, model_profile_store, voice_profiles, live)
    # 皮肤档案可经 0005 固件下发固定参数子集；资源 assets 仍不在这条通路中。
    register_round_skin_routes(
        app, round_skin_store or RoundSkinStore(ROOT), client, operation_lock,
    )
    register_round_wallpaper_routes(
        app,
        round_wallpaper_library or RoundWallpaperLibrary(ROOT / "data" / "round-screen" / "wallpapers"),
        client,
        round_wallpaper_delivery,
        operation_lock,
    )
    delivery_runner = None
    if round_wallpaper_delivery is not None:
        async def start_wallpaper_delivery(_app):
            nonlocal delivery_runner
            delivery_runner = web.AppRunner(round_wallpaper_delivery.app(), access_log=None)
            await delivery_runner.setup()
            await web.TCPSite(
                delivery_runner,
                round_wallpaper_delivery.listen_address,
                round_wallpaper_delivery.port,
            ).start()

        async def stop_wallpaper_delivery(_app):
            if delivery_runner is not None:
                await delivery_runner.cleanup()

        app.on_startup.append(start_wallpaper_delivery)
        app.on_cleanup.append(stop_wallpaper_delivery)
    # 不能证明后台算法空闲时，自动重开保守拒绝；当前Hy日用已暂停这些后台入口。
    maintenance.supported = runtime is not None
    app.on_cleanup.append(close)
    return app


def main():
    parser = argparse.ArgumentParser(description="智慧圆屏本机控制台（不会自动启动小智）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", type=Path, help="已有日用数据库路径，用于定位聊天、角色等本机配置")
    parser.add_argument("--allow-memory-delete", action="store_true", help="允许网页删除 Hy 记忆条目")
    parser.add_argument("--allow-memory-correction", action="store_true", help="允许网页纠正 Hy 记忆条目")
    parser.add_argument("--enable-chat", action="store_true", help="开启网页聊天及 Hy-Memory")
    parser.add_argument("--enable-voice-preemptive", action="store_true",
                        default=os.environ.get("LONGMEMORY_PREEMPTIVE_ENABLED") == "1",
                        help="显式开启受限语音候选宿主；只经原免费网关，不改变正式EOU")
    parser.add_argument("--memory-audit-log", type=Path, help="共享记忆 Runtime 的脱敏审计日志")
    parser.add_argument("--assistant-role", choices=("大肥鱼", "plain_v1", "elysia_v1"), default="大肥鱼")
    parser.add_argument("--xiaozhi-server", type=Path, help="允许用户确认后同步角色到此小智目录；不会自动修改配置或重启")
    parser.add_argument("--model-profile", choices=("campus", "official"), default="campus",
                        help="标记本进程实际加载的本机模型配置档")
    parser.add_argument("--memory-backend", choices=("hy_memory",),
                        default="hy_memory", help="标记本次圆屏进程实际选择的记忆后端")
    parser.add_argument("--tts-backend", choices=("edge", "voxcpm2", "sanotts", "cosyvoice3"),
                        default="edge", help="标记本次圆屏语音选择的 TTS 后端")
    parser.add_argument("--ffmpeg-dir", type=Path,
                        help="已安装的 ffmpeg/ffprobe 目录；只用于本机动态壁纸转码")
    parser.add_argument("--wallpaper-lan-ip",
                        help="动态壁纸投递专用 RFC1918 IPv4；仅圆屏模式设置")
    parser.add_argument("--launcher-status-file", type=Path,
                        help="启动面板运行快照；只读展示，不据此控制进程")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port 必须在 1024–65535 之间")
    if args.allow_memory_delete and args.database is None:
        parser.error("启用删除前必须用 --database 指定已有数据库")
    if args.allow_memory_correction and args.database is None:
        parser.error("启用纠正前必须用 --database 指定已有数据库")
    if args.enable_chat and args.database is None:
        parser.error("启用文字聊天前必须用 --database 指定已有数据库")
    if args.memory_audit_log and not args.enable_chat:
        parser.error("记忆审计日志仅在启用文字聊天/共享 Runtime 时有效")
    chat_backend = None
    if args.enable_chat:
        from longmemory.adapters.llm.fake import FakeAnswerGenerator
        from longmemory.adapters.llm.openai_compatible import OpenAICompatibleAnswerGenerator
        from longmemory.infrastructure.config.hy_deployment import build_daily_hy_runtime
        from .chat_backend import ChatBackend

        runtime = None
        try:
            role_prompt = (ROOT / "src/longmemory/prompts/personas" / (args.assistant_role + ".txt")).read_text(encoding="utf-8")
            role_prompt = role_prompt.replace("<memory></memory>", "（证据见独立 memory_evidence 消息。）")
            runtime = build_daily_hy_runtime(ROOT)
            settings = runtime.external_model_settings("answer")
            generator = (FakeAnswerGenerator() if settings.provider == "fake" else
                         OpenAICompatibleAnswerGenerator(settings, role_prompt=role_prompt))
            chat_backend = ChatBackend(runtime.database, generator, provider=settings.provider,
                                       model=settings.model or "fake", role=args.assistant_role,
                                       runtime=runtime, model_endpoint=settings.base_url or None,
                                       sidecar_database=args.database)
        except Exception:
            if runtime is not None:
                runtime.close()
            parser.error("无法开启 Hy-Memory 聊天，请检查日用数据库、Hy 配置和模型服务。")
    if not all((ROOT / "web" / path).is_file() for path, _mime in STATIC_FILES.values()):
        parser.error("控制台静态资源缺失；当前入口需要从完整源代码仓库可编辑安装后启动")
    runtime_token = os.environ.get("LONGMEMORY_RUNTIME_TOKEN")
    if runtime_token is not None and re.fullmatch(r"[0-9a-f]{64}", runtime_token) is None:
        parser.error("LONGMEMORY_RUNTIME_TOKEN 必须是启动器生成的 64 位小写十六进制值")
    print(f"控制台：http://127.0.0.1:{args.port}；仅本机访问，Ctrl+C 停止。")
    if chat_backend:
        print("网页聊天与圆屏已装配 Hy-Memory。")
    audit_handler = configure_file_logging(args.memory_audit_log) if args.memory_audit_log else None
    try:
        from longmemory.infrastructure.config.model_profiles import ModelProfileStore
        from longmemory.infrastructure.config.tts_backends import TTSBackendStore
        wallpaper_delivery = None
        if args.wallpaper_lan_ip:
            import ipaddress
            try:
                address = ipaddress.IPv4Address(args.wallpaper_lan_ip)
            except ipaddress.AddressValueError:
                parser.error("壁纸投递地址必须是有效 IPv4")
            if not any(address in ipaddress.ip_network(network) for network in (
                "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
            )):
                parser.error("壁纸投递只允许明确的 RFC1918 局域网 IPv4")
            wallpaper_delivery = RoundWallpaperDeliveryService(str(address))
        web.run_app(create_app(port=args.port, allow_memory_delete=args.allow_memory_delete,
                               allow_memory_correction=args.allow_memory_correction,
                               chat_backend=chat_backend,
                               instance_id=os.environ.get("LONGMEMORY_LAUNCHER_INSTANCE"), xiaozhi_server=args.xiaozhi_server,
                               memory_runtime_token=runtime_token, qq_directory=ROOT / "local/runtime/companion",
                               voice_proposals_enabled=args.enable_voice_preemptive,
                               model_profile_store=ModelProfileStore(ROOT, current_profile=args.model_profile),
                               tts_backend_store=TTSBackendStore(ROOT, current_backend=args.tts_backend),
                               round_wallpaper_library=RoundWallpaperLibrary(
                                   ROOT / "data" / "round-screen" / "wallpapers",
                                   ffmpeg_dir=args.ffmpeg_dir,
                               ),
                               round_wallpaper_delivery=wallpaper_delivery,
                               launcher_status_file=args.launcher_status_file,
                               observability_root=ROOT),
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
