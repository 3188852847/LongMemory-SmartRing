"""把本机控制桥的结果收窄为网页需要的字段，不向浏览器泄露令牌。"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import aiohttp

from .protocol import BridgeError, round_skin, safe_reason
from .projections import (
    activated_wallpaper,
    announcement_queued,
    deactivated_wallpaper,
    device_status,
    hardware_status,
    read_volume,
    rolled_back_wallpaper,
    round_skin_update,
    screen_update,
    speech_stop,
    staged_wallpaper,
    volume_update,
    wallpaper_status,
)


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
        return device_status(data)

    async def read_status(self) -> dict:
        data = await self._request("GET", "/api/device/status")
        return hardware_status(data)

    async def read_volume(self) -> dict:
        data = await self._request("GET", "/api/device/volume")
        return read_volume(data)

    async def set_volume(self, volume: int) -> dict:
        if type(volume) is not int or not 5 <= volume <= 60:
            raise BridgeError("invalid_volume", 400)
        data = await self._request("POST", "/api/device/volume", {"volume": volume})
        return volume_update(data, volume)

    async def stop_speech(self) -> dict:
        data = await self._request("POST", "/api/device/speech/stop")
        return speech_stop(data)

    async def set_screen(self, field: str, value: object) -> dict:
        if ((field == "brightness" and (type(value) is not int or not 5 <= value <= 100))
                or (field == "theme" and value not in {"light", "dark"})
                or field not in {"brightness", "theme"}):
            raise BridgeError("invalid_screen_setting", 400)
        data = await self._request("POST", "/api/device/screen", {field: value})
        return screen_update(data, value)

    async def read_round_skin(self) -> dict:
        data = await self._request("GET", "/api/device/round-skin")
        return round_skin(data)

    async def set_round_skin(self, skin: dict) -> dict:
        requested = round_skin(skin)
        data = await self._request("POST", "/api/device/round-skin", requested)
        return round_skin_update(data, requested)

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
        return staged_wallpaper(
            data, item_id=item_id, sha256=sha256, size_bytes=size_bytes,
        )

    async def read_round_wallpaper(self) -> dict:
        data = await self._request("GET", "/api/device/round-wallpaper")
        return wallpaper_status(data)

    async def activate_round_wallpaper(self, staged: dict) -> dict:
        fields = {"wallpaper_api", "slot", "wallpaper_id", "sha256", "size_bytes", "state"}
        if not isinstance(staged, dict) or set(staged) != fields or staged.get("state") != "staged_verified":
            raise BridgeError("round_wallpaper_stage_invalid", 400)
        data = await self._request(
            "POST", "/api/device/round-wallpaper/activate", staged,
            timeout_seconds=120,
        )
        return activated_wallpaper(data, staged)

    async def rollback_round_wallpaper(self) -> dict:
        data = await self._request(
            "POST", "/api/device/round-wallpaper/rollback", timeout_seconds=120,
        )
        return rolled_back_wallpaper(data)

    async def deactivate_round_wallpaper(self) -> dict:
        data = await self._request(
            "POST", "/api/device/round-wallpaper/deactivate", timeout_seconds=120,
        )
        return deactivated_wallpaper(data)

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
        return announcement_queued(data, expires_at_ms)
