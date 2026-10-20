"""平台语义任务白名单；参数既不能选择SDK方法，也不能授予执行未来意图的权限。"""

def validate_semantic_request(operation, arguments):
    keys = {"semantic_status": set(), "semantic_task": {"task_id"},
            "semantic_cancel": {"task_id"},
            "semantic_enqueue": {"task_id", "kind", "max_batches"}}
    if operation not in keys or not isinstance(arguments, dict) or set(arguments) != keys[operation]:
        raise ValueError("hy_semantic_request_invalid")
    if "task_id" in arguments:
        value = arguments["task_id"]
        if (not isinstance(value, str) or not value.strip() or len(value) > 256
                or value in {".", ".."} or any(ord(char) < 32 or char in "/\\" for char in value)):
            raise ValueError("hy_semantic_request_invalid")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("hy_semantic_request_invalid") from None
    if operation == "semantic_enqueue" and (not isinstance(arguments["kind"], str)
            or arguments["kind"] not in {"evolve", "intention_maintenance"}
            or type(arguments["max_batches"]) is not int or not 1 <= arguments["max_batches"] <= 4):
        raise ValueError("hy_semantic_request_invalid")
