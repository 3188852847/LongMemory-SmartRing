"""仅转译网页请求；数据库工作在线程中完成，避免锁等待阻塞音量接口。"""

import asyncio
import re

from aiohttp import web
from ..memory_backend import MemoryAccessError


def register_memory_routes(app, backend):
    async def invoke(function, *args, **kwargs):
        try:
            return web.json_response(await asyncio.to_thread(function, *args, **kwargs))
        except MemoryAccessError as error:
            return web.json_response({"error": error.code}, status=error.status)

    async def config(_request):
        return web.json_response(backend.info())

    async def listing(request):
        values = request.query
        if (set(values) - {"q", "state", "offset", "limit"}
                or any(len(values.getall(key)) != 1 for key in values)):
            raise web.HTTPBadRequest()
        query = values.get("q", "").strip()
        state = values.get("state", "active")
        try:
            offset, limit = int(values.get("offset", "0")), int(values.get("limit", "25"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        if len(query) > 200 or state not in {"active", "retired", "all"} or not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise web.HTTPBadRequest()
        return await invoke(backend.list_page, query=query, state=state, offset=offset, limit=limit)

    async def source_listing(request):
        values = request.query
        if (set(values) - {"q", "role", "link_state", "offset", "limit"}
                or any(len(values.getall(key)) != 1 for key in values)):
            raise web.HTTPBadRequest()
        query = values.get("q", "").strip()
        role, link_state = values.get("role", "all"), values.get("link_state", "all")
        try:
            offset, limit = int(values.get("offset", "0")), int(values.get("limit", "25"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        if (len(query) > 200 or role not in {"all", "user", "assistant"}
                or link_state not in {"all", "linked", "unlinked"}
                or not 0 <= offset <= 100000 or not 1 <= limit <= 100):
            raise web.HTTPBadRequest()
        return await invoke(
            backend.list_sources,
            query=query, role=role, link_state=link_state, offset=offset, limit=limit,
        )

    async def source_detail(request):
        source_id = request.match_info["source_id"]
        if not source_id or len(source_id) > 128 or any(ord(c) < 32 for c in source_id):
            raise web.HTTPBadRequest()
        return await invoke(backend.get_source, source_id)

    async def detail(request):
        memory_id = request.match_info["memory_id"]
        if not memory_id or len(memory_id) > 128 or any(ord(c) < 32 for c in memory_id):
            raise web.HTTPBadRequest()
        if request.method == "GET":
            return await invoke(backend.get, memory_id)
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if (not isinstance(body, dict) or set(body) != {"revision", "confirm_delete"}
                or body["confirm_delete"] is not True or not isinstance(body["revision"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", body["revision"])):
            raise web.HTTPBadRequest()
        return await invoke(backend.delete, memory_id, body["revision"])

    async def correction(request):
        memory_id = request.match_info["memory_id"]
        if not memory_id or len(memory_id) > 128 or any(ord(c) < 32 for c in memory_id):
            raise web.HTTPBadRequest()
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if (not isinstance(body, dict)
                or set(body) != {"revision", "corrected_content", "correction_kind", "confirm_correction"}
                or body["correction_kind"] != "error"
                or body["confirm_correction"] is not True
                or not isinstance(body["corrected_content"], str)
                or not body["corrected_content"].strip()
                or len(body["corrected_content"].strip()) > 1000
                or not isinstance(body["revision"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", body["revision"])):
            raise web.HTTPBadRequest()
        return await invoke(
            backend.correct,
            memory_id,
            body["corrected_content"].strip(),
            body["revision"],
        )

    async def change(request):
        memory_id = request.match_info["memory_id"]
        if not memory_id or len(memory_id) > 128 or any(ord(c) < 32 for c in memory_id):
            raise web.HTTPBadRequest()
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if (not isinstance(body, dict)
                or set(body) != {"revision", "new_content", "effective_at", "change_kind", "confirm_change"}
                or body["change_kind"] != "fact_changed"
                or body["confirm_change"] is not True
                or not isinstance(body["new_content"], str)
                or not body["new_content"].strip()
                or len(body["new_content"].strip()) > 1000
                or not isinstance(body["effective_at"], str)
                or not 1 <= len(body["effective_at"]) <= 64
                or not isinstance(body["revision"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", body["revision"])):
            raise web.HTTPBadRequest()
        return await invoke(
            backend.record_change,
            memory_id,
            body["new_content"].strip(),
            body["effective_at"],
            body["revision"],
        )

    async def scenario_listing(request):
        values = request.query
        if (set(values) - {"state", "offset", "limit"}
                or any(len(values.getall(key)) != 1 for key in values)):
            raise web.HTTPBadRequest()
        try:
            offset, limit = int(values.get("offset", "0")), int(values.get("limit", "25"))
        except ValueError:
            raise web.HTTPBadRequest() from None
        state = values.get("state", "all")
        if (state not in {"all", "candidate", "active", "rejected", "stale"}
                or not 0 <= offset <= 100000 or not 1 <= limit <= 100):
            raise web.HTTPBadRequest()
        return await invoke(backend.list_scenarios, state=state, offset=offset, limit=limit)

    async def scenario_collection(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        ids = body.get("source_memory_ids") if isinstance(body, dict) else None
        if (not isinstance(body, dict)
                or set(body) != {"title", "summary", "source_memory_ids", "confirm_candidate"}
                or body.get("confirm_candidate") is not True
                or not isinstance(body.get("title"), str)
                or not 1 <= len(body["title"].strip()) <= 120
                or not isinstance(body.get("summary"), str)
                or not 1 <= len(body["summary"].strip()) <= 2000
                or not isinstance(ids, list) or not 2 <= len(ids) <= 20
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in ids)
                or len(set(ids)) != len(ids)):
            raise web.HTTPBadRequest()
        return await invoke(backend.create_scenario, title=body["title"].strip(),
                            summary=body["summary"].strip(), source_memory_ids=ids)

    async def scenario_detail(request):
        scenario_id = request.match_info["scenario_id"]
        if not scenario_id or len(scenario_id) > 128 or any(ord(c) < 32 for c in scenario_id):
            raise web.HTTPBadRequest()
        return await invoke(backend.get_scenario, scenario_id)

    async def scenario_review(request):
        scenario_id = request.match_info["scenario_id"]
        if request.content_type != "application/json" or not scenario_id or len(scenario_id) > 128:
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if (not isinstance(body, dict)
                or set(body) != {"decision", "expected_revision", "confirm_review"}
                or body.get("decision") not in {"accepted", "rejected"}
                or type(body.get("expected_revision")) is not int
                or body["expected_revision"] < 1
                or body.get("confirm_review") is not True):
            raise web.HTTPBadRequest()
        return await invoke(backend.review_scenario, scenario_id,
                            decision=body["decision"], expected_revision=body["expected_revision"])

    app.router.add_get("/api/memory-config", config, allow_head=False)
    app.router.add_get("/api/memories", listing, allow_head=False)
    app.router.add_get("/api/source-messages", source_listing, allow_head=False)
    app.router.add_get("/api/source-messages/{source_id}", source_detail, allow_head=False)
    app.router.add_get("/api/memories/{memory_id}", detail, allow_head=False)
    app.router.add_delete("/api/memories/{memory_id}", detail)
    app.router.add_post("/api/memories/{memory_id}/corrections", correction)
    app.router.add_post("/api/memories/{memory_id}/changes", change)
    app.router.add_get("/api/scenarios", scenario_listing, allow_head=False)
    app.router.add_post("/api/scenarios", scenario_collection)
    app.router.add_get("/api/scenarios/{scenario_id}", scenario_detail, allow_head=False)
    app.router.add_post("/api/scenarios/{scenario_id}/reviews", scenario_review)
