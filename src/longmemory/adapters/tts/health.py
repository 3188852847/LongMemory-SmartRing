"""启动器、小智入口和网页共用的环回 TTS 就绪探测，仅依赖标准库。"""

import http.client
import json


def ready_health(backend: str, port: int, *, timeout: float) -> dict:
    """返回身份相符的已就绪响应；旧 CosyVoice 可忽略精简请求，仍按上限读取。"""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if backend == "cosyvoice3":
            connection.request("GET", "/health", headers={"Prefer": "return=minimal"})
            # 旧服务的完整响应含至多 100 条请求记录。
            limit = 1024 * 1024
        else:
            connection.request("GET", "/health")
            limit = 4096
        response = connection.getresponse()
        if response.status != 200:
            return {}
        raw = response.read(limit + 1)
        if len(raw) > limit:
            return {}
        body = json.loads(raw)
        if isinstance(body, dict) and body.get("provider") == backend and body.get("ready") is True:
            return body
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    return {}
