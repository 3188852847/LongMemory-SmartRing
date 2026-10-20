"""持久语义后台的固定HTTP门；窥视不创建Runtime，写操作不绕过管理授权。"""

import asyncio
from datetime import UTC, datetime

from aiohttp import web

from longmemory.application.semantic_tasks import validate_semantic_request
from longmemory.methods.contracts import UnsupportedCapabilityError
from longmemory.methods.hy_memory.administration import HyManagementConflict, HyManagementUncertain
from longmemory.methods.hy_memory.sdk_bridge import HyResponseError
from longmemory.methods.hy_memory.semantic import SemanticBusy
from longmemory.methods.hy_memory.layer_data import HyLayerDataBusy
from ..method_management import invoke_hy_management


def register_hy_semantic_routes(app, runtime_provider, *, allow_management=False):
    async def invoke(operation, arguments):
        def call():
            runtime = runtime_provider()
            if runtime is None:
                raise RuntimeError("hy_semantic_unavailable")
            return invoke_hy_management(runtime, operation, **arguments)
        try:
            result = await asyncio.to_thread(call)
            if operation in {"semantic_status", "semantic_task"}:
                if not isinstance(result, dict) or "observed_at" in result:
                    raise RuntimeError("hy_semantic_envelope_conflict")
                result = {**result, "observed_at": datetime.now(UTC).isoformat()}
            return web.json_response(result)
        except UnsupportedCapabilityError:
            return web.json_response({"error": "memory_backend_capability_unsupported"}, status=501)
        except (SemanticBusy, HyLayerDataBusy):
            return web.json_response({"error": "hy_semantic_busy"}, status=503)
        except HyResponseError as error:
            # 现有JSONL RPC保留固定异常类型、不透传正文。只读单任务的确定性
            # LookupError可以映射不存在；其他SDK失败继续保持不确定/不可用。
            if operation in {"semantic_task", "semantic_cancel"} and str(error) == "hy_worker_operation_failed_LookupError_state_unknown":
                return web.json_response({"error": "hy_semantic_task_not_found"}, status=404)
            return web.json_response({"error": "hy_semantic_unavailable"}, status=503)
        except LookupError:
            return web.json_response({"error": "hy_semantic_task_not_found"}, status=404)
        except HyManagementConflict:
            return web.json_response({"error": "hy_semantic_conflict"}, status=409)
        except HyManagementUncertain:
            return web.json_response({"error": "hy_semantic_outcome_uncertain"}, status=503)
        except ValueError as error:
            if str(error) == "memory_write_paused":
                return web.json_response({"error": "memory_write_paused"}, status=403)
            return web.json_response({"error": "hy_semantic_operation_rejected"}, status=409)
        except (HyResponseError, RuntimeError, TypeError, KeyError) as error:
            code = "hy_semantic_busy" if str(error) == "hy_semantic_busy" else "hy_semantic_unavailable"
            return web.json_response({"error": code}, status=503)

    async def read(request):
        if request.query or request.can_read_body:
            raise web.HTTPBadRequest()
        operation = "semantic_task" if "task_id" in request.match_info else "semantic_status"
        arguments = {"task_id": request.match_info["task_id"]} if operation == "semantic_task" else {}
        try:
            validate_semantic_request(operation, arguments)
        except ValueError:
            raise web.HTTPBadRequest() from None
        return await invoke(operation, arguments)

    async def mutate(request):
        if not allow_management:
            return web.json_response({"error": "hy_management_write_disabled"}, status=403)
        if request.query or request.content_type != "application/json":
            raise web.HTTPBadRequest()
        operation = "semantic_cancel" if "task_id" in request.match_info else "semantic_enqueue"
        try:
            data = await request.clone(client_max_size=4096).json()
            if operation == "semantic_cancel":
                if data != {}:
                    raise ValueError()
                data = {"task_id": request.match_info["task_id"]}
            validate_semantic_request(operation, data)
        except (ValueError, TypeError, UnicodeError):
            raise web.HTTPBadRequest() from None
        return await invoke(operation, data)

    base = "/api/memory-engine/hy/semantic"
    app.router.add_get(base + "/status", read, allow_head=False)
    app.router.add_get(base + "/tasks/{task_id}", read, allow_head=False)
    app.router.add_post(base + "/tasks", mutate)
    app.router.add_post(base + "/tasks/{task_id}/cancel", mutate)
