"""圆屏皮肤档案 API；真机写入必须由用户触发并以固件回读为准。"""

from aiohttp import web

from longmemory.adapters.device_control.xiaozhi import BridgeError


def register_round_skin_routes(app, store, bridge, operation_lock):
    async def listing(_request):
        try:
            return web.json_response({"enabled": True, **store.describe()})
        except (OSError, ValueError, UnicodeError):
            return web.json_response({"error": "round_skins_unavailable"}, status=503)

    async def select(request):
        try:
            if request.content_type != "application/json":
                raise ValueError("invalid_body")
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"skin_id"} or not isinstance(body["skin_id"], str):
                raise ValueError("invalid_body")
            return web.json_response({"enabled": True, **store.select(body["skin_id"])})
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_round_skin"}, status=400)

    async def device_skin(request):
        if operation_lock.locked():
            return web.json_response({"error": "operation_busy"}, status=409)
        async with operation_lock:
            try:
                if request.method == "GET":
                    return web.json_response(await bridge.read_round_skin())
                if request.content_type != "application/json":
                    raise ValueError("invalid_body")
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {"skin_id"} or not isinstance(body["skin_id"], str):
                    raise ValueError("invalid_body")
                payload = store.device_payload(body["skin_id"])
                result = await bridge.set_round_skin(payload)
                if result.get("verified") is True:
                    store.select(body["skin_id"])
                return web.json_response(result)
            except (ValueError, TypeError, UnicodeError, OSError):
                return web.json_response({"error": "invalid_round_skin"}, status=400)
            except BridgeError as error:
                # 只回显适配器固定错误码，不向浏览器暴露固件或网络原文。
                return web.json_response({"error": error.code}, status=error.status)

    app.router.add_get("/api/round-skins", listing, allow_head=False)
    app.router.add_put("/api/round-skins/selection", select)
    app.router.add_get("/api/round-skins/device", device_skin, allow_head=False)
    app.router.add_post("/api/round-skins/device", device_skin)
