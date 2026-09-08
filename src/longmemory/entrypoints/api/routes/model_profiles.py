"""本机模型配置档 API；读取响应绝不包含密钥。"""

from aiohttp import web


def register_model_profile_routes(app, store, voice=None):
    async def listing(_request):
        if store is None:
            return web.json_response({"enabled": False})
        result = {"enabled": True, **store.describe()}
        if voice is not None:
            result["voice"] = await voice.describe()
        return web.json_response(result)

    async def save(request):
        if store is None:
            return web.json_response({"error": "model_profiles_disabled"}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"error": "invalid_body"}, status=400)
        try:
            result = store.save(request.match_info["profile"], await request.json())
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_model_profile"}, status=400)
        payload = {"enabled": True, **result}
        if voice is not None:
            payload["voice"] = await voice.describe()
        return web.json_response(payload)

    async def select_voice(request):
        if store is None or voice is None:
            return web.json_response({"error": "voice_model_profiles_disabled"}, status=403)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"profile"}:
                raise ValueError("invalid_body")
            result = await voice.select(body["profile"])
        except (ValueError, TypeError, UnicodeError, OSError):
            return web.json_response({"error": "invalid_voice_model_profile"}, status=400)
        return web.json_response(result)

    async def check_voice(_request):
        if voice is None:
            return web.json_response({"error": "voice_model_profiles_disabled"}, status=403)
        try:
            return web.json_response(await voice.check())
        except ValueError:
            return web.json_response({"error": "voice_model_check_busy"}, status=409)

    app.router.add_get("/api/model-profiles", listing, allow_head=False)
    app.router.add_put("/api/model-profiles/{profile}", save)
    app.router.add_put("/api/model-profiles/voice/selection", select_voice)
    app.router.add_post("/api/model-profiles/voice/check", check_voice)
