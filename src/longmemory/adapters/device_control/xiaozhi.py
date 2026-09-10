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
    "status_readback_unavailable", "value_outside_device_schema",
    "brightness_out_of_range", "theme_invalid",
    "round_skin_invalid", "round_skin_readback_invalid", "round_skin_readback_mismatch",
    "round_wallpaper_stage_invalid", "round_wallpaper_readback_invalid",
    "round_wallpaper_readback_mismatch", "round_wallpaper_delivery_unavailable",
    "round_wallpaper_restart_not_acknowledged",
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

    async def _request(self, method: str, path: str, body=None, *, timeout_seconds=18) -> dict:
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
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
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
        required_flags = (
            "ready", "read_volume_supported", "set_volume_supported",
            "announcement_supported", "announcement_ready", "user_session_active",
        )
        optional_flags = ("read_status_supported", "set_brightness_supported", "set_theme_supported", "aec_advertised")
        if type(count) is not int or count < 0 or any(type(data.get(k)) is not bool for k in required_flags):
            raise BridgeError("bridge_invalid_response", 502)
        if any(k in data and type(data[k]) is not bool for k in optional_flags):
            raise BridgeError("bridge_invalid_response", 502)
        if data["ready"] and count != 1:
            raise BridgeError("bridge_invalid_response", 502)
        result = {"connection_count": count, **{k: data[k] for k in required_flags},
                  **{k: data.get(k, False) for k in optional_flags}}
        result["allowed_volume"] = {"minimum": 5, "maximum": 60}
        if "reason" in data:
            result["reason"] = safe_reason(data["reason"])
        if "announcement_reason" in data:
            result["announcement_reason"] = safe_reason(data["announcement_reason"])
        return result

    async def read_status(self) -> dict:
        data = await self._request("GET", "/api/device/status")
        allowed = {"volume", "brightness", "theme", "battery", "network", "chip"}
        if not data or set(data) - allowed:
            raise BridgeError("bridge_invalid_response", 502)
        if "volume" in data and not volume_value(data["volume"]):
            raise BridgeError("bridge_invalid_response", 502)
        if "brightness" in data and not volume_value(data["brightness"]):
            raise BridgeError("bridge_invalid_response", 502)
        if "theme" in data and data["theme"] not in {"light", "dark"}:
            raise BridgeError("bridge_invalid_response", 502)
        battery = data.get("battery")
        if battery is not None and (not isinstance(battery, dict) or set(battery) != {"level", "charging"}
                or not volume_value(battery.get("level")) or type(battery.get("charging")) is not bool):
            raise BridgeError("bridge_invalid_response", 502)
        network = data.get("network")
        if network is not None and (not isinstance(network, dict) or set(network) != {"signal"}
                or network.get("signal") not in {"strong", "medium", "weak"}):
            raise BridgeError("bridge_invalid_response", 502)
        chip = data.get("chip")
        if chip is not None and (not isinstance(chip, dict) or set(chip) != {"temperature"}
                or type(chip.get("temperature")) not in {int, float} or not -40 <= chip["temperature"] <= 125):
            raise BridgeError("bridge_invalid_response", 502)
        return data

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

    async def set_screen(self, field: str, value: object) -> dict:
        if ((field == "brightness" and (type(value) is not int or not 5 <= value <= 100))
                or (field == "theme" and value not in {"light", "dark"})
                or field not in {"brightness", "theme"}):
            raise BridgeError("invalid_screen_setting", 400)
        data = await self._request("POST", "/api/device/screen", {field: value})
        if (data.get("requested_value") != value or data.get("acknowledged") is not True
                or type(data.get("verified")) is not bool):
            raise BridgeError("bridge_invalid_response", 502)
        if data["verified"] and data.get("readback_value") != value:
            raise BridgeError("bridge_invalid_response", 502)
        result = {key: data.get(key) for key in (
            "requested_value", "previous_value", "acknowledged", "readback_value", "verified"
        )}
        if "reason" in data:
            result["reason"] = safe_reason(data["reason"])
        return result

    async def read_round_skin(self) -> dict:
        data = await self._request("GET", "/api/device/round-skin")
        return self._round_skin(data)

    async def set_round_skin(self, skin: dict) -> dict:
        requested = self._round_skin(skin)
        data = await self._request("POST", "/api/device/round-skin", requested)
        if (data.get("requested_skin_id") != requested["skin_id"]
                or data.get("requested_manifest_sha256") != requested["manifest_sha256"]
                or data.get("acknowledged") is not True
                or type(data.get("verified")) is not bool):
            raise BridgeError("bridge_invalid_response", 502)
        result = {
            "requested_skin_id": data["requested_skin_id"],
            "requested_manifest_sha256": data["requested_manifest_sha256"],
            "acknowledged": True,
            "verified": data["verified"],
        }
        if "device_skin" in data:
            result["device_skin"] = self._round_skin(data["device_skin"])
        if result["verified"] and result.get("device_skin") != requested:
            raise BridgeError("bridge_invalid_response", 502)
        if "reason" in data:
            result["reason"] = safe_reason(data["reason"])
        return result

    async def stage_round_wallpaper(
        self, *, item_id: str, sha256: str, size_bytes: int, url: str,
    ) -> dict:
        if (not re.fullmatch(r"wallpaper-[0-9a-f]{20}", item_id)
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or type(size_bytes) is not int or not 0 < size_bytes <= 4 * 1024 * 1024
                or not isinstance(url, str)):
            raise BridgeError("round_wallpaper_stage_invalid", 400)
        data = await self._request(
            "POST", "/api/device/round-wallpaper/stage",
            {"item_id": item_id, "sha256": sha256, "size_bytes": size_bytes, "url": url},
            timeout_seconds=150,
        )
        fields = {"wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes",
                  "state", "operation_id"}
        if (set(data) != fields or data.get("wallpaper_api") != 1
                or data.get("slot") not in {"a", "b"}
                or data.get("wallpaper_id") != item_id or data.get("sha256") != sha256
                or data.get("size_bytes") != size_bytes
                or data.get("state") != "staged_verified"
                or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("operation_id", "")))):
            raise BridgeError("bridge_invalid_response", 502)
        return data

    async def read_round_wallpaper(self) -> dict:
        data = await self._request("GET", "/api/device/round-wallpaper")
        fields = {"wallpaper_api", "active_valid", "active_slot", "active_wallpaper_id",
                  "active_sha256", "active_size_bytes", "rollback_available"}
        if not isinstance(data, dict) or set(data) != fields or data.get("wallpaper_api") != 1:
            raise BridgeError("bridge_invalid_response", 502)
        if type(data.get("active_valid")) is not bool or type(data.get("rollback_available")) is not bool:
            raise BridgeError("bridge_invalid_response", 502)
        if data["active_valid"]:
            valid = (data.get("active_slot") in {"a", "b"}
                     and re.fullmatch(r"wallpaper-[0-9a-f]{20}", str(data.get("active_wallpaper_id", "")))
                     and re.fullmatch(r"[0-9a-f]{64}", str(data.get("active_sha256", "")))
                     and type(data.get("active_size_bytes")) is int
                     and 0 < data["active_size_bytes"] <= 4 * 1024 * 1024)
        else:
            valid = (data.get("active_slot") == "" and data.get("active_wallpaper_id") == ""
                     and data.get("active_sha256") == "" and data.get("active_size_bytes") == 0
                     and data.get("rollback_available") is False)
        if not valid:
            raise BridgeError("bridge_invalid_response", 502)
        return data

    async def activate_round_wallpaper(self, staged: dict) -> dict:
        fields = {"wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes", "state"}
        if not isinstance(staged, dict) or set(staged) != fields or staged.get("state") != "staged_verified":
            raise BridgeError("round_wallpaper_stage_invalid", 400)
        data = await self._request(
            "POST", "/api/device/round-wallpaper/activate", staged,
            timeout_seconds=120,
        )
        expected = {**staged, "state": "activated_restarting"}
        operation_id = data.pop("operation_id", None)
        if data != expected or not re.fullmatch(r"[0-9a-f]{32}", str(operation_id or "")):
            raise BridgeError("bridge_invalid_response", 502)
        return {**data, "operation_id": operation_id}

    async def rollback_round_wallpaper(self) -> dict:
        data = await self._request(
            "POST", "/api/device/round-wallpaper/rollback", timeout_seconds=120,
        )
        fields = {"wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes",
                  "state", "operation_id"}
        if (set(data) != fields or data.get("wallpaper_api") != 1
                or data.get("slot") not in {"a", "b"}
                or data.get("state") != "rollback_restarting"
                or not re.fullmatch(r"wallpaper-[0-9a-f]{20}", str(data.get("wallpaper_id", "")))
                or not re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256", "")))
                or type(data.get("size_bytes")) is not int
                or not 0 < data["size_bytes"] <= 4 * 1024 * 1024
                or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("operation_id", "")))):
            raise BridgeError("bridge_invalid_response", 502)
        return data

    @staticmethod
    def _round_skin(value: object) -> dict:
        fields = {
            "skin_api", "skin_id", "manifest_sha256", "background", "foreground", "muted",
            "accent", "listening", "thinking", "happy", "concerned", "error",
            "eye_width", "eye_height", "mouth_width",
        }
        colors = fields - {"skin_api", "skin_id", "manifest_sha256", "eye_width", "eye_height", "mouth_width"}
        if not isinstance(value, dict) or set(value) != fields or value.get("skin_api") != 1:
            raise BridgeError("bridge_invalid_response", 502)
        if (not isinstance(value.get("skin_id"), str)
                or re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", value["skin_id"]) is None
                or not isinstance(value.get("manifest_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", value["manifest_sha256"]) is None
                or any(type(value.get(key)) is not int or not 0 <= value[key] <= 0xFFFFFF for key in colors)):
            raise BridgeError("bridge_invalid_response", 502)
        for key, minimum, maximum in (("eye_width", 12, 36), ("eye_height", 18, 48), ("mouth_width", 20, 64)):
            if type(value.get(key)) is not int or not minimum <= value[key] <= maximum:
                raise BridgeError("bridge_invalid_response", 502)
        return value

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
