"""技术验证用本机 HTTP 窄接口。复用小智现有 aiohttp，不新增依赖。

无网页、无 CORS、拒绝带 Origin 的浏览器请求，只接受带本地令牌的客户端。
后续控制台必须重新设计同源会话/CSRF，不能直接把令牌放进网页。
"""

import re
import secrets
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from device_control import ControlError


PORT = 8766
TOKEN_FILE = Path(__file__).resolve().parents[3] / "data/control/device-control.token"


def remember_background(control, connection):
    """关闭前保留工作者句柄；固定上游close会清空executor但不等待它结束。"""
    background_idle(control)
    objects = [getattr(connection, 'executor', None)]
    tts = getattr(connection, 'tts', None)
    objects.extend(getattr(tts, name, None) for name in ('tts_priority_thread', 'audio_play_priority_thread'))
    for worker in objects:
        if worker is not None and not isinstance(worker, (ThreadPoolExecutor, threading.Thread)):
            control._network_unknown_background = True
        elif worker is not None and worker not in control._network_retiring:
            control._network_retiring.append(worker)


def background_idle(control):
    pending = []
    for worker in control._network_retiring:
        try:
            if isinstance(worker, ThreadPoolExecutor):
                busy = not worker._shutdown or any(thread.is_alive() for thread in tuple(worker._threads))
            elif isinstance(worker, threading.Thread):
                busy = worker.is_alive()
            else:
                busy = True  # 未知工作者不能被猜成空闲。
        except Exception:
            busy = True
        if busy:
            pending.append(worker)
    control._network_retiring = pending
    return not pending and not control._network_unknown_background


def read_token(path=TOKEN_FILE):
    value = path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("控制令牌文件格式错误；未输出内容。")
    return value


def ensure_token(path=TOKEN_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="ascii") as handle:
            handle.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    return read_token(path)


def create_app(control, token, port=PORT):
    from aiohttp import web
    control._network_drain_until = 0
    control._network_incoming = 0
    control._network_retiring = []
    control._network_unknown_background = False

    async def network_maintenance(request):
        data = await request.json()
        instance = os.environ.get('LONGMEMORY_LAUNCHER_INSTANCE')
        if (not instance or not isinstance(data, dict) or set(data) != {'instance', 'draining'}
                or data['instance'] != instance or type(data['draining']) is not bool):
            return web.json_response({'error': 'maintenance_identity_mismatch'}, status=409)
        if not data['draining']:
            control._network_drain_until = 0
        elif (control.connections or control._network_incoming or control.operation_lock.locked()
              or not background_idle(control)):
            return web.json_response({'error': 'network_restart_busy'}, status=409)
        else:
            control._network_drain_until = time.monotonic() + 60
        return web.json_response({'instance': instance, 'draining': data['draining']})

    @web.middleware
    async def guard(request, handler):
        # 固定 Host 防止 DNS rebinding；不依赖 CORS 来阻止带副作用的请求。
        if (request.remote != "127.0.0.1"
                or request.headers.get("Host") != f"127.0.0.1:{port}"
                or "Origin" in request.headers
                or "Sec-Fetch-Site" in request.headers):
            return web.json_response({"error": "local_cli_only"}, status=403)
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            response = await handler(request)
        except ControlError as exc:
            response = web.json_response({"error": exc.code}, status=exc.status)
        except web.HTTPException as exc:
            response = web.json_response({"error": "http_request_rejected"}, status=exc.status)
        except Exception:
            response = web.json_response({"error": "control_internal_error"}, status=500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def status(request):
        background_idle(control)
        return web.json_response(control.status())

    async def read_volume(request):
        return web.json_response(await control.read_volume())

    async def read_status(request):
        return web.json_response(await control.read_status())

    async def set_volume(request):
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        if not isinstance(body, dict) or set(body) != {"volume"}:
            raise ControlError("invalid_fields", 400)
        return web.json_response(await control.set_volume(body["volume"]))

    async def set_screen(request):
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        if not isinstance(body, dict) or len(body) != 1:
            raise ControlError("invalid_fields", 400)
        if set(body) == {"brightness"}:
            return web.json_response(await control.set_brightness(body["brightness"]))
        if set(body) == {"theme"}:
            return web.json_response(await control.set_theme(body["theme"]))
        raise ControlError("invalid_fields", 400)

    async def round_skin(request):
        if request.method == "GET":
            return web.json_response(await control.read_round_skin())
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        return web.json_response(await control.set_round_skin(body))

    async def stage_round_wallpaper(request):
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        fields = {"item_id", "sha256", "size_bytes", "url"}
        if not isinstance(body, dict) or set(body) != fields:
            raise ControlError("invalid_fields", 400)
        return web.json_response(await control.stage_round_wallpaper(**body))

    async def get_round_wallpaper(_request):
        return web.json_response(await control.read_round_wallpaper())

    async def activate_round_wallpaper(request):
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        return web.json_response(await control.activate_round_wallpaper(body))

    async def rollback_round_wallpaper(request):
        if request.content_length not in (None, 0):
            raise ControlError("invalid_fields", 400)
        return web.json_response(await control.rollback_round_wallpaper())

    async def deactivate_round_wallpaper(request):
        if request.content_length not in (None, 0):
            raise ControlError("invalid_fields", 400)
        return web.json_response(await control.deactivate_round_wallpaper())

    async def announce(request):
        if request.content_type != "application/json":
            raise ControlError("json_required", 415)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise ControlError("invalid_json", 400) from None
        if not isinstance(body, dict) or set(body) != {"text", "expires_at_ms"}:
            raise ControlError("invalid_fields", 400)
        return web.json_response(
            await control.announce(body["text"], body["expires_at_ms"])
        )

    async def stop_speech(request):
        if request.content_length not in (None, 0):
            raise ControlError("invalid_fields", 400)
        return web.json_response(await control.stop_speech())

    app = web.Application(middlewares=[guard], client_max_size=1024)
    app.router.add_post('/api/network-maintenance', network_maintenance)
    app.router.add_get("/api/device", status, allow_head=False)
    app.router.add_get("/api/device/volume", read_volume, allow_head=False)
    app.router.add_post("/api/device/volume", set_volume)
    app.router.add_get("/api/device/status", read_status, allow_head=False)
    app.router.add_post("/api/device/screen", set_screen)
    app.router.add_get("/api/device/round-skin", round_skin, allow_head=False)
    app.router.add_post("/api/device/round-skin", round_skin)
    app.router.add_post("/api/device/round-wallpaper/stage", stage_round_wallpaper)
    app.router.add_get("/api/device/round-wallpaper", get_round_wallpaper, allow_head=False)
    app.router.add_post("/api/device/round-wallpaper/activate", activate_round_wallpaper)
    app.router.add_post("/api/device/round-wallpaper/rollback", rollback_round_wallpaper)
    app.router.add_post("/api/device/round-wallpaper/deactivate", deactivate_round_wallpaper)
    app.router.add_post("/api/device/announcement", announce)
    app.router.add_post("/api/device/speech/stop", stop_speech)
    return app


def install_control_server(server_class, connection_class):
    """随小智 WebSocket 任务启动/清理，避免另一个线程跨事件循环操作连接。"""
    from device_control import DeviceControl, install_connection_tracking
    original = server_class.start

    async def start(server):
        from aiohttp import web
        config = server.config
        # 设备控制身份不属于某一种记忆算法。即使本次选择小智摘要或
        # nomem，仍复用已审计的单设备 ID，而不让控制能力随算法消失。
        allowed_id = config["Memory"]["LongMemory"]["allowed_device_id"]
        control = DeviceControl(allowed_id)
        runner = web.AppRunner(create_app(control, ensure_token()), access_log=None)
        previous_handle = connection_class.handle_connection
        previous_close = connection_class.close
        async def close(connection, *args, **kwargs):
            try:
                remember_background(control, connection)
            except Exception:
                control._network_unknown_background = True
            return await previous_close(connection, *args, **kwargs)
        connection_class.close = close
        previous_accept = server._handle_connection
        async def accept(websocket):
            if control._network_drain_until > time.monotonic():
                await websocket.close(code=1013)
                return
            control._network_incoming += 1
            try:
                return await previous_accept(websocket)
            finally:
                control._network_incoming -= 1
        server._handle_connection = accept
        install_connection_tracking(connection_class, control)
        try:
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", PORT).start()
            print(f"设备控制已开启：http://127.0.0.1:{PORT}（仅令牌客户端，无网页）", flush=True)
            return await original(server)
        except OSError:
            print("设备控制端口启动失败；未自动换端口，请检查 8766 是否占用。", flush=True)
            raise
        finally:
            server._handle_connection = previous_accept
            connection_class.handle_connection = previous_handle
            connection_class.close = previous_close
            await runner.cleanup()

    server_class.start = start
