"""把本机控制桥的结果收窄为网页需要的字段，不向浏览器泄露令牌。"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import aiohttp


class BridgeError(Exception):
    """只携带固定错误码；上游原文可能含设备数据，不能直接显示。"""

    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status


REASONS = frozenset({
    "ambiguous_device_connections", "tool_schema_unsupported", "device_rejected",
    "unexpected_device_result", "device_connection_changed", "tool_not_allowed",
    "device_timeout_outcome_unknown", "device_call_failed_outcome_unknown",
    "volume_readback_unavailable", "control_busy", "volume_outside_device_schema",
    "set_not_acknowledged_outcome_unknown",
    "device_offline", "device_not_ready", "tools_not_ready", "readback_mismatch",
    "volume_out_of_range", "tool_unavailable",
    "invalid_announcement", "invalid_expiry", "announcement_expired",
    "tts_not_ready", "device_busy", "announcement_enqueue_failed",
})


def safe_reason(value: object) -> str:
    return value if isinstance(value, str) and value in REASONS else "bridge_error"


def volume_value(value: object) -> bool:
    return type(value) is int and 0 <= value <= 100


class XiaozhiControlClient:
    """仅连回环控制端口，关闭代理、重定向和自动重试。"""

    def __init__(self, token_file: Path):
        self.token_file = token_file
        self._session = None

    async def close(self):
        if self._session is not None:
            await self._session.close()

    async def _request(self, method: str, path: str, body=None) -> dict:
        try:
            # 每次读取，以便小智重建令牌后无需重启网页服务；内容从不打印。
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise BridgeError("bridge_not_configured") from None
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise BridgeError("bridge_not_configured")
        if self._session is None:
            self._session = aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=18)
            )
        try:
            async with self._session.request(
                method, "http://127.0.0.1:8766" + path,
                headers={"Authorization": "Bearer " + token}, json=body,
                allow_redirects=False,
            ) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    raw.extend(chunk)
                    if len(raw) > 16384:
                        raise BridgeError("bridge_invalid_response", 502)
                if response.status in {401, 403}:
                    raise BridgeError("bridge_auth_failed")
                if 300 <= response.status < 400:
                    raise BridgeError("bridge_invalid_response", 502)
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise BridgeError("bridge_invalid_response", 502)
                if response.status != 200:
                    raise BridgeError(safe_reason(data.get("error")), 409)
                return data
        except asyncio.TimeoutError:
            # 写请求超时并不等于没执行，页面必须要求重新读取，不能自动重发。
            raise BridgeError("bridge_timeout", 504) from None
        except (aiohttp.ClientError, OSError):
            raise BridgeError("bridge_unavailable") from None
        except (ValueError, UnicodeError):
            raise BridgeError("bridge_invalid_response", 502) from None

    async def status(self) -> dict:
        data = await self._request("GET", "/api/device")
        count = data.get("connection_count")
        flags = (
            "ready", "read_volume_supported", "set_volume_supported",
            "announcement_supported", "announcement_ready", "user_session_active",
        )
        if type(count) is not int or count < 0 or any(type(data.get(k)) is not bool for k in flags):
            raise BridgeError("bridge_invalid_response", 502)
        if data["ready"] and count != 1:
            raise BridgeError("bridge_invalid_response", 502)
        result = {"connection_count": count, **{k: data[k] for k in flags}}
        result["allowed_volume"] = {"minimum": 5, "maximum": 60}
        if "reason" in data:
            result["reason"] = safe_reason(data["reason"])
        if "announcement_reason" in data:
            result["announcement_reason"] = safe_reason(data["announcement_reason"])
        return result

    async def read_volume(self) -> dict:
        data = await self._request("GET", "/api/device/volume")
        if not volume_value(data.get("volume")):
            raise BridgeError("bridge_invalid_response", 502)
        return {"volume": data["volume"]}

    async def set_volume(self, volume: int) -> dict:
        if type(volume) is not int or not 5 <= volume <= 60:
            raise BridgeError("invalid_volume", 400)
        data = await self._request("POST", "/api/device/volume", {"volume": volume})
        if (type(data.get("requested_volume")) is not int or data["requested_volume"] != volume or data.get("acknowledged") is not True
                or type(data.get("verified")) is not bool
                or not volume_value(data.get("previous_volume"))
                or (data.get("readback_volume") is not None and not volume_value(data["readback_volume"]))):
            raise BridgeError("bridge_invalid_response", 502)
        if data["verified"] and data.get("readback_volume") != volume:
            raise BridgeError("bridge_invalid_response", 502)
        result = {key: data.get(key) for key in (
            "requested_volume", "previous_volume", "acknowledged", "readback_volume", "verified"
        )}
        if "reason" in data:
            result["reason"] = safe_reason(data["reason"])
        return result

    async def announce(self, text: str, expires_at: datetime) -> dict:
        """请求现有小智 TTS 队列接收短文本，不声称设备已经播放。"""

        if (not isinstance(text, str) or text != text.strip() or not text
                or len(text) > 80 or any(ord(char) < 32 for char in text)):
            raise BridgeError("invalid_announcement", 400)
        if (not isinstance(expires_at, datetime) or expires_at.tzinfo is None
                or expires_at.utcoffset() is None):
            raise BridgeError("invalid_expiry", 400)
        expires_at_ms = int(expires_at.timestamp() * 1000)
        data = await self._request(
            "POST", "/api/device/announcement",
            {"text": text, "expires_at_ms": expires_at_ms},
        )
        operation_id = data.get("operation_id")
        if (not isinstance(operation_id, str)
                or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
                or data.get("state") != "queued"
                or data.get("playback_acknowledgement") != "unavailable"
                or data.get("expires_at_ms") != expires_at_ms):
            raise BridgeError("bridge_invalid_response", 502)
        # 只保留编排需要的非敏感字段；上游额外数据不向应用层扩散。
        return {
            "operation_id": operation_id,
            "state": "queued",
            "playback_acknowledgement": "unavailable",
            "expires_at_ms": expires_at_ms,
        }
