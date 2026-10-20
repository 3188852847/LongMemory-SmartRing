"""受信小智候选RPC；复用/internal/memory鉴权，不增直连或供应商密钥投影。"""

from aiohttp import web

from longmemory.application.voice_proposal_contract import (
    ACTIONS, BODY_LIMIT, validate_voice_proposal_request, validate_voice_proposal_response,
)
from longmemory.methods.contracts import UnsupportedCapabilityError


def register_voice_proposal_routes(app, host):
    def handler(action):
        async def perform(request):
            if request.query or request.content_type != "application/json":
                return web.json_response({"error": "voice_proposal_request_invalid"}, status=400)
            try:
                body = await request.clone(client_max_size=BODY_LIMIT).json()
                validate_voice_proposal_request(action, body)
            except (ValueError, TypeError, UnicodeError, RecursionError, web.HTTPRequestEntityTooLarge):
                return web.json_response({"error": "voice_proposal_request_invalid"}, status=400)
            try:
                result = await getattr(host, action)(body)
                validate_voice_proposal_response(action, result)
                return web.json_response(result)
            except UnsupportedCapabilityError:
                return web.json_response({"error": "voice_proposal_unavailable"}, status=503)
            except ValueError:
                return web.json_response({"error": "voice_proposal_rejected"}, status=409)
            except RuntimeError as error:
                if str(error) == "voice_proposal_rejected":
                    return web.json_response({"error": "voice_proposal_rejected"}, status=409)
                return web.json_response({"error": "voice_proposal_unavailable"}, status=503)
            except (TypeError, KeyError):
                return web.json_response({"error": "voice_proposal_unavailable"}, status=503)
        return perform
    for action in ACTIONS:
        app.router.add_post("/api/internal/memory/proposals/" + action, handler(action))

    async def close(_app):
        result = await host.aclose()
        if result is False or (isinstance(result, dict) and result.get("closed") is False):
            app.logger.warning("voice_proposal_shutdown_unconfirmed")
    app.on_cleanup.append(close)
