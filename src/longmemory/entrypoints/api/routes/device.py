"""智能圆屏设备控制 HTTP 路由。

路由只做请求边界校验、并发门控和 BridgeError 投影；设备协议与连接状态继续由
注入的客户端负责，应用组合根不需要了解每条控制命令。
"""

from aiohttp import web

from longmemory.adapters.device_control.xiaozhi import BridgeError


def register_device_routes(app, client, operation_lock):
    async def device(_request):
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
                            or type(body["volume"]) is not int or not 5 <= body["volume"] <= 100):
                        return web.json_response({"error": "invalid_volume"}, status=400)
                    data = await client.set_volume(body["volume"])
                return web.json_response(data)
            except BridgeError as error:
                return web.json_response({"error": error.code}, status=error.status)

    async def device_snapshot(_request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        async with operation_lock:
            try:
                return web.json_response(await client.read_status())
            except BridgeError as error:
                return web.json_response({"error": error.code}, status=error.status)

    async def screen(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        async with operation_lock:
            try:
                if request.content_type != "application/json":
                    return web.json_response({"error": "invalid_body"}, status=400)
                body = await request.json()
                if not isinstance(body, dict) or len(body) != 1:
                    return web.json_response({"error": "invalid_screen_setting"}, status=400)
                if (set(body) == {"brightness"} and type(body["brightness"]) is int
                        and 5 <= body["brightness"] <= 100):
                    data = await client.set_screen("brightness", body["brightness"])
                elif set(body) == {"theme"} and body["theme"] in {"light", "dark"}:
                    data = await client.set_screen("theme", body["theme"])
                else:
                    return web.json_response({"error": "invalid_screen_setting"}, status=400)
                return web.json_response(data)
            except (ValueError, UnicodeError):
                return web.json_response({"error": "invalid_body"}, status=400)
            except BridgeError as error:
                return web.json_response({"error": error.code}, status=error.status)

    async def stop_speech(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        if request.content_length not in (None, 0):
            return web.json_response({"error": "invalid_body"}, status=400)
        async with operation_lock:
            try:
                return web.json_response(await client.stop_speech())
            except BridgeError as error:
                return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/device", device, allow_head=False)
    app.router.add_get("/api/device/volume", volume, allow_head=False)
    app.router.add_post("/api/device/volume", volume)
    app.router.add_get("/api/device/snapshot", device_snapshot, allow_head=False)
    app.router.add_post("/api/device/screen", screen)
    app.router.add_post("/api/device/speech/stop", stop_speech)
