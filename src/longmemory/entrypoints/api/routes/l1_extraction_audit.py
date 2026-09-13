"""日常 L1 提取账本的本机只读 HTTP 入口。"""

import asyncio
import re

from aiohttp import web
from pydantic import ValidationError

from longmemory.entrypoints.api.contracts import L1ExtractionRetryRequest


def register_l1_extraction_audit_routes(app, backend):
    async def listing(request):
        if set(request.query) - {"limit"} or any(
            len(request.query.getall(key)) != 1 for key in request.query
        ):
            raise web.HTTPBadRequest()
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        if not 1 <= limit <= 100:
            raise web.HTTPBadRequest()
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=503)
        return web.json_response(await asyncio.to_thread(
            backend.list_l1_extraction_audit, limit=limit,
        ))

    app.router.add_get(
        "/api/l1-extraction-audit", listing, allow_head=False,
    )

    async def retry(request):
        source_message_id = request.match_info["source_message_id"]
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", source_message_id):
            raise web.HTTPBadRequest()
        if backend is None:
            return web.json_response({"error": "chat_disabled"}, status=503)
        if request.content_type != "application/json":
            return web.json_response({"error": "invalid_l1_retry"}, status=400)
        try:
            payload = L1ExtractionRetryRequest.model_validate(await request.json())
        except (ValidationError, ValueError, TypeError):
            return web.json_response({"error": "invalid_l1_retry"}, status=400)
        try:
            value = await asyncio.to_thread(
                backend.retry_l1_extraction, source_message_id,
                **payload.model_dump(),
            )
        except ValueError as error:
            code = str(error)
            status = 404 if code == "l1_retry_source_not_found" else (
                409 if code in {
                    "l1_retry_stale", "l1_retry_not_available", "l1_retry_busy",
                    "l1_retry_runtime_closing",
                } else 400
            )
            return web.json_response({"error": code}, status=status)
        return web.json_response(value, status=202)

    app.router.add_post(
        "/api/l1-extraction-audit/{source_message_id}/retry", retry,
    )
