"""供应商缓存证据白名单；不记录提示词，也不由耗时推断服务端能力。"""


def _tokens(value):
    return type(value) is int and value >= 0


def cache_evidence(usage, *, completed):
    """缺字段保持unknown；零命中只说明本次未命中，不能说明不支持。"""
    result = {"state": "unknown", "source": None, "hit_tokens": None,
              "miss_tokens": None, "completed": bool(completed)}
    if not isinstance(usage, dict):
        return result
    hit_key, miss_key = "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"
    details = usage.get("prompt_tokens_details")
    if hit_key in usage or miss_key in usage:
        hit, miss = usage.get(hit_key), usage.get(miss_key)
        result["source"] = "deepseek_usage"
        valid = _tokens(hit) and _tokens(miss)
        if "prompt_tokens" in usage:
            valid = valid and _tokens(usage["prompt_tokens"]) and hit + miss == usage["prompt_tokens"]
        if isinstance(details, dict) and "cached_tokens" in details:
            valid = valid and _tokens(details["cached_tokens"]) and hit == details["cached_tokens"]
    elif isinstance(details, dict) and "cached_tokens" in details:
        hit, prompt = details["cached_tokens"], usage.get("prompt_tokens")
        result["source"] = "compatible_usage"
        valid = _tokens(hit) and _tokens(prompt) and hit <= prompt
        miss = prompt - hit if valid else None
    else:
        return result
    if not valid:
        return dict(result, state="invalid")
    return dict(result, state="reported_hit" if hit else "reported_miss",
                hit_tokens=hit, miss_tokens=miss)


def has_final_text(packet, *, streaming):
    """只能在answer_content投影之后调用；工具参数/思考字段/空白不计有效文本。"""
    for choice in packet.get("choices") or []:
        message = choice.get("delta" if streaming else "message") or {}
        text = message.get("content")
        if isinstance(text, str) and text.strip():
            return True
    return False
