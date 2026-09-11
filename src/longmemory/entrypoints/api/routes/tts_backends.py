"""TTS 下次启动选择 API；不热切换、不启动本地模型。"""

from aiohttp import web


def register_tts_backend_routes(app, store, runtime_status):
    def voice_running():
        status = runtime_status()
        return status.get("services", {}).get("voice") in {"running", "ready"}

    async def listing(_request):
        if store is None:
            return web.json_response({"enabled": False})
        return web.json_response({"enabled": True, **store.describe(voice_running=voice_running())})

    async def select(request):
        if store is None:
            return web.json_response({"error": "tts_backends_disabled"}, status=403)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"backend"}:
                raise ValueError("invalid_body")
            result = store.select(body["backend"], voice_running=voice_running())
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_tts_backend"}, status=400)
        return web.json_response({"enabled": True, **result})

    app.router.add_get("/api/tts-backends", listing, allow_head=False)
    app.router.add_put("/api/tts-backends/selection", select)
