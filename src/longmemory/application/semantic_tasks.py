"""平台语义任务白名单；参数既不能选择SDK方法，也不能授予执行未来意图的权限。"""

import re


def validate_semantic_request(operation, arguments):
    keys = {"semantic_status": set(), "semantic_task": {"task_id"},
            "semantic_cancel": {"task_id"},
            "semantic_enqueue": {"task_id", "kind", "max_batches"}}
    if operation not in keys or not isinstance(arguments, dict) or set(arguments) != keys[operation]:
        raise ValueError("hy_semantic_request_invalid")
    if "task_id" in arguments and (not isinstance(arguments["task_id"], str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,96}", arguments["task_id"]) is None):
        raise ValueError("hy_semantic_request_invalid")
    if operation == "semantic_enqueue" and (not isinstance(arguments["kind"], str)
            or arguments["kind"] not in {"evolve", "intention_maintenance"}
            or type(arguments["max_batches"]) is not int or not 1 <= arguments["max_batches"] <= 4):
        raise ValueError("hy_semantic_request_invalid")
