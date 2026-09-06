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

    async def scenario_source_inbox(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(backend.list_scenario_source_inbox)

    async def scenario_collection(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        ids = body.get("source_memory_ids") if isinstance(body, dict) else None
        old_fields = {"title", "summary", "source_memory_ids", "creation_kind", "confirm_candidate"}
        new_fields = old_fields | {"valid_from", "valid_to"}
        if (not isinstance(body, dict)
                or set(body) not in (old_fields, new_fields)
                or body.get("confirm_candidate") is not True
                or body.get("creation_kind") not in {"manual", "model_assisted"}
                or not isinstance(body.get("title"), str)
                or not 1 <= len(body["title"].strip()) <= 120
                or not isinstance(body.get("summary"), str)
                or not 1 <= len(body["summary"].strip()) <= 2000
                or not isinstance(ids, list) or not 2 <= len(ids) <= 20
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in ids)
                or len(set(ids)) != len(ids)):
            raise web.HTTPBadRequest()
        for field in ("valid_from", "valid_to"):
            value = body.get(field)
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 64):
                raise web.HTTPBadRequest()
        return await invoke(backend.create_scenario, title=body["title"].strip(),
                            summary=body["summary"].strip(), source_memory_ids=ids,
                            creation_kind=body["creation_kind"],
                            valid_from=body.get("valid_from"), valid_to=body.get("valid_to"))

    async def scenario_proposal(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        ids = body.get("source_memory_ids") if isinstance(body, dict) else None
        if (not isinstance(body, dict)
                or set(body) != {"source_memory_ids", "confirm_model_call"}
                or body.get("confirm_model_call") is not True
                or not isinstance(ids, list) or not 2 <= len(ids) <= 20
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in ids)
                or len(set(ids)) != len(ids)):
            raise web.HTTPBadRequest()
        return await invoke(backend.preview_scenario, source_memory_ids=ids)

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

    async def scenario_lifecycle(request):
        scenario_id = request.match_info["scenario_id"]
        if request.content_type != "application/json" or not scenario_id or len(scenario_id) > 128:
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        if (not isinstance(body, dict)
                or set(body) != {"action", "expected_revision", "confirm_action"}
                or body.get("action") != "manual_end"
                or type(body.get("expected_revision")) is not int
                or body["expected_revision"] < 1
                or body.get("confirm_action") is not True):
            raise web.HTTPBadRequest()
        return await invoke(backend.end_scenario, scenario_id,
                            expected_revision=body["expected_revision"])

    async def persona_listing(request):
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
        return await invoke(backend.list_personas, state=state, offset=offset, limit=limit)

    async def persona_profile(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(backend.get_persona_profile)

    async def persona_source_options(request):
        if request.query:
            raise web.HTTPBadRequest()
        return await invoke(backend.list_persona_source_options)

    async def persona_collection(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        sources = body.get("sources") if isinstance(body, dict) else None
        fields = {"kind", "basis", "label", "statement", "sources",
                  "valid_from", "valid_to", "confirm_candidate"}
        extended_fields = fields | {"creation_kind"}
        if (not isinstance(body, dict) or set(body) not in (fields, extended_fields)
                or body.get("confirm_candidate") is not True
                or body.get("creation_kind", "manual") not in {"manual", "model_assisted"}
                or body.get("kind") not in {"preference", "habit", "interaction_style", "behavior_pattern"}
                or body.get("basis") not in {"user_declared", "system_inferred"}
                or not isinstance(body.get("label"), str)
                or not 1 <= len(body["label"].strip()) <= 120
                or not isinstance(body.get("statement"), str)
                or not 1 <= len(body["statement"].strip()) <= 1000
                or not isinstance(sources, list) or not 1 <= len(sources) <= 20):
            raise web.HTTPBadRequest()
        source_keys = []
        for item in sources:
            if (not isinstance(item, dict) or set(item) != {"layer", "id"}
                    or item.get("layer") not in {"l1", "l2"}
                    or not isinstance(item.get("id"), str)
                    or not 1 <= len(item["id"]) <= 128):
                raise web.HTTPBadRequest()
            source_keys.append((item["layer"], item["id"]))
        if len(set(source_keys)) != len(source_keys):
            raise web.HTTPBadRequest()
        for field in ("valid_from", "valid_to"):
            value = body[field]
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 64):
                raise web.HTTPBadRequest()
        return await invoke(
            backend.create_persona, kind=body["kind"], basis=body["basis"],
            label=body["label"].strip(), statement=body["statement"].strip(),
            sources=sources, valid_from=body["valid_from"], valid_to=body["valid_to"],
            creation_kind=body.get("creation_kind", "manual"),
        )

    async def persona_proposal(request):
        if request.content_type != "application/json":
            raise web.HTTPBadRequest()
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        sources = body.get("sources") if isinstance(body, dict) else None
        if (not isinstance(body, dict)
                or set(body) != {"basis", "sources", "confirm_model_call"}
                or body.get("basis") not in {"user_declared", "system_inferred"}
                or body.get("confirm_model_call") is not True
                or not isinstance(sources, list) or not 1 <= len(sources) <= 20):
            raise web.HTTPBadRequest()
        keys = []
        for item in sources:
            if (not isinstance(item, dict) or set(item) != {"layer", "id"}
                    or item.get("layer") not in {"l1", "l2"}
                    or not isinstance(item.get("id"), str)
                    or not 1 <= len(item["id"]) <= 128):
                raise web.HTTPBadRequest()
            keys.append((item["layer"], item["id"]))
        if len(set(keys)) != len(keys):
            raise web.HTTPBadRequest()
        return await invoke(
            backend.preview_persona, basis=body["basis"], sources=sources,
        )

    async def persona_detail(request):
        persona_id = request.match_info["persona_id"]
        if not persona_id or len(persona_id) > 128 or any(ord(c) < 32 for c in persona_id):
            raise web.HTTPBadRequest()
        return await invoke(backend.get_persona, persona_id)

    async def persona_review(request):
        persona_id = request.match_info["persona_id"]
        if request.content_type != "application/json" or not persona_id or len(persona_id) > 128:
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
        return await invoke(
            backend.review_persona, persona_id, decision=body["decision"],
            expected_revision=body["expected_revision"],
        )

    app.router.add_get("/api/memory-config", config, allow_head=False)
    app.router.add_get("/api/memories", listing, allow_head=False)
    app.router.add_get("/api/source-messages", source_listing, allow_head=False)
    app.router.add_get("/api/source-messages/{source_id}", source_detail, allow_head=False)
    app.router.add_get("/api/memories/{memory_id}", detail, allow_head=False)
    app.router.add_delete("/api/memories/{memory_id}", detail)
    app.router.add_post("/api/memories/{memory_id}/corrections", correction)
    app.router.add_post("/api/memories/{memory_id}/changes", change)
    app.router.add_get("/api/scenarios", scenario_listing, allow_head=False)
    app.router.add_get("/api/scenario-source-inbox", scenario_source_inbox, allow_head=False)
    app.router.add_post("/api/scenarios", scenario_collection)
    app.router.add_post("/api/scenario-proposals", scenario_proposal)
    app.router.add_get("/api/scenarios/{scenario_id}", scenario_detail, allow_head=False)
    app.router.add_post("/api/scenarios/{scenario_id}/reviews", scenario_review)
    app.router.add_post("/api/scenarios/{scenario_id}/lifecycle", scenario_lifecycle)
    app.router.add_get("/api/personas", persona_listing, allow_head=False)
    app.router.add_get("/api/persona-profile", persona_profile, allow_head=False)
    app.router.add_get("/api/persona-source-options", persona_source_options, allow_head=False)
    app.router.add_post("/api/personas", persona_collection)
    app.router.add_post("/api/persona-proposals", persona_proposal)
    app.router.add_get("/api/personas/{persona_id}", persona_detail, allow_head=False)
    app.router.add_post("/api/personas/{persona_id}/reviews", persona_review)
